import time
import os
import cv2
import math
import numpy as np
import threading

try:
    import dlib
    import face_recognition
    USE_DLIB = True
    print("[시스템] dlib 및 face_recognition 환경이 감지되었습니다. 원본 dlib 엔진을 사용합니다.")
except ImportError:
    USE_DLIB = False
    print("[시스템] dlib 또는 face_recognition이 없습니다. MediaPipe 및 CV2 우회 엔진을 활성화합니다.")

# MediaPipe는 우회 엔진의 필수 의존성이므로 dlib이 없을 때만 동적 임포트 처리합니다.
try:
    import mediapipe as mp
except ImportError:
    print("[오류] MediaPipe 라이브러리가 설치되어 있지 않습니다. 'pip install mediapipe'를 실행해 주세요.")

# 모델 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_PATH = os.path.join(BASE_DIR, "models", "blaze_face_short_range.tflite")

class MuggleBlockerDetector:
    # 초기화
    def __init__(self, model_path = DEFAULT_MODEL_PATH):
        self.use_dlib = USE_DLIB

        # 공통 프레임 제어 변수
        self.frame_width = 0
        self.frame_height = 0
        # 최적화 시 사용
        self.frame_skip_interval = 3 # 프레임 스킵 주기
        self.frame_count = 0 # 프레임 세기
        self.intrusion_threshold = 3.0 # 3초 이상 감지
        self.muggle_detected_start_time = None # 3초 타이머 시작 시간
        self.missed_frame_count = 0 # 프레임이 확확 튀는 것 방지
        self.roi_box = None # roi 박스 그리기 위한 bbox 저장
        self.roi_rate = 0.5
        self.cropped_box = None # 크롭한 박스 좌표
        
        # 비동기 동기화 변수
        self.frame_offsets = {} # 타임스탬프 별 오프셋 저장. (offset_x, offset_y, crop_w, crop_h)
        self.latest_faces = [] # 콜백에서 변환된 얼굴 리스트 저장

        # 신원 검문 변수
        self.last_recognition_time = time.time()
        self.recognition_interval = 2.0  # 시간 지정, 60초 기본
        self.is_stranger_detected = False
        self.is_recognizing = False


        # 사용자 얼굴 등록
        self.user_face_image = None # 웹캠에서 받아오기
        self.user_encoding = None

        # 옵션 설정
        try:
            BaseOptions = mp.tasks.BaseOptions
            FaceDetector = mp.tasks.vision.FaceDetector
            FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions
            VisionRunningMode = mp.tasks.vision.RunningMode

            options = FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=model_path),
                running_mode=VisionRunningMode.LIVE_STREAM,
                result_callback=self._save_result_callback
            )
            self.detector = FaceDetector.create_from_options(options)
        except Exception as e:
            print(f"[오류] MediaPipe 모델 로드 실패: {e}")
            self.detector = None
        

        if self.use_dlib:
            # dlib 사용할 경우:
            # dlib의 얼굴 감지 모델을 선언합니다. 
            # face_recognition 패키지가 내부적으로 dlib 모델을 호출하므로, 
            # 이곳에선 감지 성능 향상에 필요한 기본 상태 및 플래그만 설정해 두면 충분합니다.
            self.dlib_detector = dlib.get_frontal_face_detector()
            print("[디텍터] dlib 정면 얼굴 검출기 로드 완료!")

    def register_user_face(self, frame_rgb):
            """본인 등록 함수 (첫 구동 시 최초 1회 호출)"""
            if self.use_dlib:
                # ==========================================================
                # [엔진 A] dlib 기반 등록: Face Encoding 추출하여 등록
                # ==========================================================
                try:
                    # RGB 프레임에서 얼굴 위치를 먼저 검출합니다.
                    face_locations = face_recognition.face_locations(frame_rgb)
                    if len(face_locations) > 0:
                        # 감지된 얼굴 부위에서 128차원 고유 얼굴 벡터(encoding)를 계산해 등록합니다.
                        encodings = face_recognition.face_encodings(frame_rgb, face_locations)
                        if len(encodings) > 0:
                            self.user_encoding = encodings[0]
                            print("[디텍터] dlib 기반 사용자 고유 인코딩 등록 성공!")
                            return True
                    print("[디텍터] dlib 등록 실패: 첫 프레임에서 얼굴을 감지하지 못했습니다.")
                except Exception as e:
                    print(f"[디텍터] dlib 등록 중 예외 발생: {e}")
                return False
            else:
                # ==========================================================
                # [엔진 B] MediaPipe 기반 등록: 템플릿 이미지를 정규화하여 저장
                # ==========================================================
                gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
                h, w = gray.shape
                cx, cy = w // 2, h // 2
                self.user_encoding = cv2.resize(gray[cy-60:cy+60, cx-60:cx+60], (128, 128))
                print("[디텍터] MediaPipe 히스토그램 등록 완료!")
                return True


    # call back
    def _save_result_callback(self, result, output_image: mp.Image, timestamp_ms: int):
        # MediaPipe가 얼굴 판별을 끝낼 때마다 백그라운드에서 자동으로 호출되는 함수

        # 1. 감지 실패한다면 초기화
        if not result or not result.detections:
            self.latest_faces = []

            if timestamp_ms in self.frame_offsets:
                del self.frame_offsets[timestamp_ms]
            return
        
        # 2. 현재 프레임을 던질 때 사용한 오프셋 정보 가져오기
        offsets = self.frame_offsets.get(timestamp_ms)
        if not offsets:
            return
        
        ox, oy, cw, ch = offsets

        faces = []
        for detection in result.detections:
            # bbox 좌표 계산 
            # (크롭된 이미지를 받으므로, 전체 화면에 그리기 위해서 전체 화면에 대한 좌표 계산)
            bbox = detection.bounding_box
            real_x = int(bbox.origin_x) + ox
            real_y = int(bbox.origin_y) + oy
            boxes = [real_x, real_y, int(bbox.width), int(bbox.height)]

            # 6개 특징점 
            # (normalize된 비율을 주므로, 전체 화면에서 계산하기 위해서 전체 화면에 대한 좌표 계산)
            keypoints = []
            if detection.keypoints:
                for keypoint in detection.keypoints:
                    kp_x = int(keypoint.x * cw) + ox
                    kp_y = int(keypoint.y * ch) + oy
                    keypoints.append((kp_x, kp_y))
            # 묶어서 반환
            faces.append({
                "boxes": boxes,
                "keypoints": keypoints
            })

        # 변환 완료된 최신 좌표만 저장
        self.latest_faces = faces

    # async detection
    def process_frame(self, frame, timestamp_ms: int):
        """실시간 프레임을 주입받아 얼굴 분석 예약을 수행하는 함수"""

        if self.detector is None:
            return

         # [최적화 1] 프레임 스킵 적용
        self.frame_count += 1
        if self.frame_count % self.frame_skip_interval != 0:
            return
        
        # 가져온 프레임의 크기
        self.frame_height, self.frame_width, _ = frame.shape

        # openCV는 BGR을 MediaPipe 전용 포맷으로 변경
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # [최적화 2] ROI 추적 알고리즘 이용
        if self.roi_box == None: # AWAY, INTRUSION: 전체 화면 감지 (roi_box = None)
            # 전체 화면 기준으로 초기화
            input_image = frame_rgb
            self.cropped_box = None
            # 전체 화면으로 오프셋 초기화
            ox, oy = 0, 0 
            cw, ch = self.frame_width, self.frame_height

        else: # NORMAL: roi_box 좌표 반환(감지된 얼굴 1개 추적)
            x, y, w, h = self.roi_box # roi_box 계산을 위한 bbox 좌표

            # roi_box 계산
            x1 = max(0, int(x - w * self.roi_rate))
            x2 = min(self.frame_width, int((x+w) + w * self.roi_rate))
            y1 = max(0, int(y - h * self.roi_rate))
            y2 = min(self.frame_height, int((y+h) + h * self.roi_rate))

            # crop -> 해상도 유지를 위해 0으로 채운 뒤 해당 부분만 크롭해서 넣기
            self.cropped_box = [x1, x2, y1, y2] # 크롭 좌표
            input_image = np.zeros_like(frame_rgb) # 같은 해상도 0으로 채워서 만들기
            input_image[y1:y2, x1:x2] = frame_rgb[y1:y2, x1:x2] # 크롭된 이미지 넣기

            ox, oy = 0, 0 
            cw, ch = self.frame_width, self.frame_height

            pure_crop_image = frame_rgb[y1:y2, x1:x2] # 얼굴 인식용 순수 크롭 이미지
            target_size = (128, 128)
            pure_crop_image = cv2.resize(pure_crop_image, target_size, interpolation=cv2.INTER_AREA) # 150*150으로 변경!


        # 방금 계산한 오프셋 타임스탬프와 함께 저장
        safe_timestamp_ms = int(time.perf_counter_ns() // 1_000_000) #단조 시간 증가하는 절대 시간을 새로 만듦(메인에서 받은 timestamp_ms 중복 방지)
        self.frame_offsets[safe_timestamp_ms] = (ox, oy, cw, ch)

        # 오프셋 딕셔너리 10 이하로 유지
        if len(self.frame_offsets) > 10:
            oldest_timestamp = min(self.frame_offsets.keys())
            del self.frame_offsets[oldest_timestamp]

        # 비동기 감지 실행 (결과는 백그라운드에서 _save_result로 들어옴)
        input_image = mp.Image(image_format = mp.ImageFormat.SRGB, data = input_image)
        self.detector.detect_async(input_image, safe_timestamp_ms)

        # 검증 트리거: dlib 기반 실시간 신원 확인
        if self.use_dlib:
            if self.user_encoding is not None and self.roi_box is not None and not self.is_recognizing:
                current_time = time.time()
                if current_time - self.last_recognition_time > self.recognition_interval: # 검증 주기가 되면
                    self.last_recognition_time = current_time # 현재 시간을 마지막 인식 시간으로 갱신
                    # thread 부르기
                    thread = threading.Thread(
                        target = self._verify_identity_thread, 
                        args = (pure_crop_image.copy(), )
                    )
                    thread.start()
        else:
            current_time = time.time()
            if self.user_encoding is not None and not self.is_recognizing:
                if current_time - self.last_recognition_time > self.recognition_interval:
                    self.last_recognition_time = current_time
                    
                    thread = threading.Thread(
                        target=self._mediapipe_verify_identity_thread,
                        args=(frame_rgb.copy(),)
                    )
                    thread.start()

    # bbox 반환
    def get_bboxes(self):
        staring_faces = self._get_staring_faces()
        return [face['boxes'] for face in staring_faces]
    
    # cropped_box 반환
    def get_cropped_box(self):
        if self.cropped_box == None:
            return
        return self.cropped_box
    
    # 화면을 응시 중인 얼굴을 걸러내서 status 판단 (반환값: 'NORMAL', 'AWAY', 'INSTRUSION')
    # 핵심 판별 부분
    def get_status(self) -> str:

        # 1. [핵심 수정] 응시 여부나 침입 상태와 무조건 상관없이 ROI 추적 박스부터 업데이트!
        if len(self.latest_faces) > 0:
            new_box = self.latest_faces[0]['boxes']
            # EMA(좌표 스무딩) 적용
            if self.roi_box is None:
                self.roi_box = new_box
            else:
                alpha = 0.3
                self.roi_box = [
                    int(self.roi_box[0] * (1 - alpha) + new_box[0] * alpha),
                    int(self.roi_box[1] * (1 - alpha) + new_box[1] * alpha),
                    int(self.roi_box[2] * (1 - alpha) + new_box[2] * alpha),
                    int(self.roi_box[3] * (1 - alpha) + new_box[3] * alpha)
                ]

        staring_faces = self._get_staring_faces()
        staring_count = len(staring_faces)

        # 2. 아무도 화면을 보지 않을 때 (AWAY)
        if staring_count == 0:
            self.muggle_detected_start_time = None
            if self.missed_frame_count < 30: # 30 프레임 연속으로 감지된 경우에만 away로 바꾸기
                self.missed_frame_count += 1
                # 방금 전까지 침입자였다면, 잠깐 얼굴을 돌려도 바로 화면이 켜지지 않도록 방어
                if self.is_stranger_detected:
                    return "INTRUSION"
                return "NORMAL"
            
            # 💡 완전히 자리 비움 판정 시, 추적 박스와 침입자 플래그 모두 깔끔하게 리셋!
            self.roi_box = None
            self.is_stranger_detected = False 
            return "AWAY"

        # 3. [핵심 수정] 추적 박스 갱신과 AWAY 판정이 모두 끝난 뒤에 침입자 플래그 확인
        if self.is_stranger_detected:
            return "INTRUSION"
        
        # 4. 1명이 쳐다볼 때
        elif staring_count == 1:
            self.muggle_detected_start_time = None
            self.missed_frame_count = 0
            return "NORMAL"

        # 5. 2명 이상이 쳐다볼 때
        elif staring_count >= 2:
            self.roi_box = None
            self.missed_frame_count = 0
            # [최적화 3] 3초 이상 intrusion 감지 시 확정!
            if self.muggle_detected_start_time == None:
                self.muggle_detected_start_time = time.time()
                return "NORMAL" # 타이머 시작
            elif time.time() - self.muggle_detected_start_time > self.intrusion_threshold:
                return "INTRUSION" # 3초 지나면 감지!
            else:
                return "NORMAL" # 타이머 도는 중

    # ==========================================================
    # 백그라운드 연산 스레드 메서드 영역
    # ==========================================================

    # 1분 마다 사용자의 얼굴이 맞는지 검증
    def _verify_identity_thread(self, pure_crop_image):
        """[엔진 A] dlib 백그라운드 신원 대조 알고리즘"""
        self.is_recognizing = True # 검증 시작 (락)
        try:
            encodings = face_recognition.face_encodings(pure_crop_image)

            if len(encodings) > 0:
                match = face_recognition.compare_faces([self.user_encoding], encodings[0], tolerance=0.5)
                if not match[0]:
                    print("muggle detection!")
                    self.is_stranger_detected = True
                else:
                    print("[AI] dlib 기반 사용자 본인 확인 완료")
                    # [핵심 수정] 주인이 다시 나타나면 침입 상태 해제
                    self.is_stranger_detected = False 
            else:
                print("크롭된 이미지를 찾지 못함")

        except Exception as e:
            print(f"🚨 얼굴 검증 스레드 에러 발생: {e}")
        finally:
            self.last_recognition_time = time.time() # 검문 시간 리셋
            self.is_recognizing = False # 검증 종료 (락 해제)

    def _mediapipe_verify_identity_thread(self, frame_rgb):
        """[엔진 B] MediaPipe & OpenCV 가속 백그라운드 신원 대조 알고리즘"""
        self.is_recognizing = True
        try:
            gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
            # 템플릿 매칭 기법을 적용하여 등록된 얼굴 영역의 위치를 프레임 내에서 탐색
            result = cv2.matchTemplate(gray, self.user_encoding, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)

            print(f"[AI] 사용자 대조 연산 완료 (유사도 계수: {max_val:.2f})")

            # 임계값(Threshold)에 따른 지능형 3단계 상태 변경
            if max_val >= 0.45:
                print("normal 유지")
                # [핵심 수정] 팀원 코드의 self.status를 제거하고 초기 버전 로직으로 통일
                self.is_stranger_detected = False
            elif max_val < 0.20:
                print("muggle detection!")
                # [핵심 수정] 누락된 타이머 함수 대신 초기 버전처럼 즉각 플래그 변경
                self.is_stranger_detected = True
            else:
                pass
        except Exception as e:
            print(f"[경고] OpenCV 유사도 분석 오류: {e}")
        finally:
            self.is_recognizing = False

        
    # 응시하는지 확인 (응시하는 얼굴 카운트)
    def _get_staring_faces(self):

        staring_faces = []

        for face in self.latest_faces:
            box = face["boxes"]
            kps = face["keypoints"]

            # 예외 처리
            if len(kps) < 3:
                continue

            center_x = (kps[0][0] + kps[1][0])/2 # 얼굴 중앙 x좌표

            dx = kps[0][0] - kps[1][0]
            dy = kps[0][1] - kps[1][1]
            eye_dist = math.hypot(dx, dy) # 눈 사이 거리 (피타고라스 이용)

            if eye_dist == 0: # 0으로 나누는 것 방지
                eye_dist = 1

            nose_x = kps[2][0] # 코 끝 x좌표

            # 코가 중앙에서 얼마나 벗어났는지 비율 계산 (0.0 ~ 1.0)
            offset_ratio = abs(center_x - nose_x) / eye_dist

            if offset_ratio < 0.6:
                staring_faces.append(face)

        return staring_faces

"""
import os
import time
import cv2
import numpy as np

# 1. 환경에 따른 동적 임포트 (Dynamic Import) 처리
try:
    import dlib
    import face_recognition
    USE_DLIB = True
    print("[시스템] dlib 및 face_recognition 환경이 감지되었습니다. 원본 dlib 엔진을 사용합니다.")
except ImportError:
    USE_DLIB = False
    print("[시스템] dlib 또는 face_recognition이 없습니다. MediaPipe 및 CV2 우회 엔진을 활성화합니다.")

# MediaPipe는 우회 엔진의 필수 의존성이므로 dlib이 없을 때만 동적 임포트 처리합니다.
if not USE_DLIB:
    try:
        import mediapipe as mp
    except ImportError:
        print("[오류] MediaPipe 라이브러리가 설치되어 있지 않습니다. 'pip install mediapipe'를 실행해 주세요.")


class MuggleBlockerDetector:
    def __init__(self):
        self.use_dlib = USE_DLIB
        self.status = "NORMAL"  # 초기 상태 설정 ('NORMAL', 'AWAY', 'INTRUSION')
        self.user_encoding = None  # 사용자 등록 정보 저장 변수
        
        # 공통 프레임 제어 변수
        self.frame_width = 640
        self.frame_height = 360
        self.roi_rate = 0.2  # 얼굴 크롭 마진 비율
        self.is_recognizing = False
        self.last_recognition_time = 0
        self.recognition_interval = 2.0  # 분석 주기 (초)
        self.frame_offsets = {}  # 비동기 처리를 위한 딕셔너리
        self.current_bboxes = []  # 추가: UI로 내보낼 BBox 좌표 저장 변수

        # 최적화 변수
        self.frame_count = 0
        self.frame_skip_interval = 1
        self.intrusion_start_time = None

        if self.use_dlib:
            # ==========================================================
            # [엔진 A] 태연 님 전용 dlib / face_recognition 초기화 설정
            # ==========================================================
            # dlib의 얼굴 감지 모델을 선언합니다. 
            # face_recognition 패키지가 내부적으로 dlib 모델을 호출하므로, 
            # 이곳에선 감지 성능 향상에 필요한 기본 상태 및 플래그만 설정해 두면 충분합니다.
            self.dlib_detector = dlib.get_frontal_face_detector()
            print("[디텍터] dlib 정면 얼굴 검출기 로드 완료!")
        else:
            # ==========================================================
            # [엔진 B] 다경 님 전용 MediaPipe & TFLite 가속 초기화 설정
            # ==========================================================
            self.model_path = os.path.join(
                os.path.dirname(__file__), "models", "blaze_face_short_range.tflite"
            )
            
            # MediaPipe Face Detector 초기화 설정
            try:
                BaseOptions = mp.tasks.BaseOptions
                FaceDetector = mp.tasks.vision.FaceDetector
                FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions
                VisionRunningMode = mp.tasks.vision.RunningMode

                options = FaceDetectorOptions(
                    base_options=BaseOptions(model_asset_path=self.model_path),
                    running_mode=VisionRunningMode.LIVE_STREAM,
                    result_callback=self._save_result
                )
                self.detector = FaceDetector.create_from_options(options)
            except Exception as e:
                print(f"[오류] MediaPipe 모델 로드 실패: {e}")
                self.detector = None

    def _save_result(self, result, output_image, timestamp_ms):
        # MediaPipe 비동기 콜백 함수: 분석 결과를 처리하여 상태값 갱신
        # 감지된 얼굴이 아예 없는 경우 -> AWAY
        if not result.detections:
            self.status = "AWAY"
            return

        # 비동기 분석 예약 시점에 보관해 두었던 오프셋 가져오기
        offsets = self.frame_offsets.pop(timestamp_ms, (0, 0, self.frame_width, self.frame_height))
        ox, oy, cw, ch = offsets

        bboxes = []

        for detection in result.detections:
            bbox = detection.bounding_box
            # 프레임 내 상대 좌표를 절대 픽셀 좌표로 환산
            x = max(0, ox + bbox.origin_x)
            y = max(0, oy + bbox.origin_y)
            w = min(cw, bbox.width)
            h = min(ch, bbox.height)
            bboxes.append((x, y, w, h))

            # 얼굴 원본 이미지 슬라이싱 및 대조 연산 실행
            if self.user_encoding is not None and not self.is_recognizing:
                pass
        self.current_bboxes = bboxes

    def register_user_face(self, frame_rgb):
        # 본인 등록 함수 (첫 구동 시 최초 1회 호출)
        if self.use_dlib:
            # ==========================================================
            # [엔진 A] dlib 기반 등록: Face Encoding 추출하여 등록
            # ==========================================================
            try:
                # RGB 프레임에서 얼굴 위치를 먼저 검출합니다.
                face_locations = face_recognition.face_locations(frame_rgb)
                if len(face_locations) > 0:
                    # 감지된 얼굴 부위에서 128차원 고유 얼굴 벡터(encoding)를 계산해 등록합니다.
                    encodings = face_recognition.face_encodings(frame_rgb, face_locations)
                    if len(encodings) > 0:
                        self.user_encoding = encodings[0]
                        print("[디텍터] dlib 기반 사용자 고유 인코딩 등록 성공!")
                        return True
                print("[디텍터] dlib 등록 실패: 첫 프레임에서 얼굴을 감지하지 못했습니다.")
            except Exception as e:
                print(f"[디텍터] dlib 등록 중 예외 발생: {e}")
            return False
        else:
            # ==========================================================
            # [엔진 B] MediaPipe 기반 등록: 템플릿 이미지를 정규화하여 저장
            # ==========================================================
            gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
            h, w = gray.shape
            cx, cy = w // 2, h // 2
            self.user_encoding = cv2.resize(gray[cy-60:cy+60, cx-60:cx+60], (128, 128))
            print("[디텍터] MediaPipe 히스토그램 등록 완료!")
            return True

    def process_frame(self, frame_rgb, timestamp_ms):
        # 실시간 프레임을 주입받아 얼굴 분석 예약을 수행하는 함수 

        # [최적화] 3프레임당 1프레임만 AI 연산 수행
        self.frame_count += 1
        if self.frame_count % self.frame_skip_interval != 0:
            return
        
        if self.use_dlib:
            # ==========================================================
            # [엔진 A] dlib 기반 실시간 검출 파이프라인
            # ==========================================================
            current_time = time.time()
            if current_time - self.last_recognition_time > self.recognition_interval:
                self.last_recognition_time = current_time
                
                # 비동기식으로 dlib 검출 연산 실행 (화면 멈춤 방지)
                import threading
                thread = threading.Thread(
                    target=self._dlib_verify_identity_thread,
                    args=(frame_rgb.copy(),)
                )
                thread.start()
        else:
            # ==========================================================
            # [엔진 B] MediaPipe 기반 실시간 검출 파이프라인
            # ==========================================================
            if self.detector is None:
                return

            h, w, _ = frame_rgb.shape
            self.frame_width, self.frame_height = w, h

            # 가벼운 매핑을 위해 기본 오프셋 보관
            safe_timestamp_ms = int(time.perf_counter_ns() // 1_000_000)
            self.frame_offsets[safe_timestamp_ms] = (0, 0, w, h)

            try:
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
                self.detector.detect_async(mp_image, safe_timestamp_ms)
            except Exception:
                self.frame_offsets.pop(safe_timestamp_ms, None)

            # 일정 주기마다 히스토그램 정밀 유사도 대조 스레드 트리거
            current_time = time.time()
            if self.user_encoding is not None and not self.is_recognizing:
                if current_time - self.last_recognition_time > self.recognition_interval:
                    self.last_recognition_time = current_time
                    
                    import threading
                    thread = threading.Thread(
                        target=self._mediapipe_verify_identity_thread,
                        args=(frame_rgb.copy(),)
                    )
                    thread.start()

    def get_status(self):
        # UI 루프에서 주기적으로 상태값('NORMAL', 'AWAY', 'INTRUSION')을 수거하는 함수
        return self.status
    
    def get_bboxes(self):
        # UI 루프에서 BBox 좌표를 수거하는 함수
        return self.current_bboxes

    # ==========================================================
    # 백그라운드 연산 스레드 메서드 영역
    # ==========================================================
    
    def _dlib_verify_identity_thread(self, frame_rgb):
        # [엔진 A] dlib 백그라운드 신원 대조 알고리즘
        try:
            # 1. dlib 감지기로 이미지 내 모든 얼굴 좌표 파악
            face_locations = face_recognition.face_locations(frame_rgb)
            self.current_bboxes = [(left, top, right - left, bottom - top) for top, right, bottom, left in face_locations]
            
            # [1 단계] 얼굴이 아예 없을 때 -> AWAY
            if not face_locations:
                self.status = "AWAY"
                return
            
            # [2 단계] 얼굴이 2개 이상일 때 -> 무조건 INTRUSION 차단!
            if len(face_locations) >= 2:
                self._trigger_intrusion_timer()
                return

            # [3단계] 감지된 첫 번째 얼굴의 인코딩 백터 추출
            encodings = face_recognition.face_encodings(frame_rgb, face_locations)
            if self.user_encoding is not None and encodings:
                # 3. 등록된 주인(self.user_encoding)의 벡터와 현재 검출된 얼굴 벡터 1:1 비교
                # tolerance가 낮을수록 엄격하게 검증합니다. (보통 0.45 ~ 0.5가 적당합니다)
                matches = face_recognition.compare_faces([self.user_encoding], encodings[0], tolerance=0.45)
                
                if matches[0]:
                    self.status = "NORMAL"
                    self.intrusion_start_time = None # 💡 정상 인식 시 타이머 리셋
                    print("[AI] dlib 기반 사용자 본인 확인 완료")
                else:
                    self._trigger_intrusion_timer()
        except Exception as e:
            print(f"[경고] dlib 대조 중 에러: {e}")

    def _mediapipe_verify_identity_thread(self, frame_rgb):
        # [엔진 B] MediaPipe & OpenCV 가속 백그라운드 신원 대조 알고리즘
        self.is_recognizing = True
        try:
            gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
            # 템플릿 매칭 기법을 적용하여 등록된 얼굴 영역의 위치를 프레임 내에서 탐색
            result = cv2.matchTemplate(gray, self.user_encoding, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)

            print(f"[AI] 사용자 대조 연산 완료 (유사도 계수: {max_val:.2f})")

            # 임계값(Threshold)에 따른 지능형 3단계 상태 변경
            if max_val >= 0.45:
                self.status = "NORMAL"
                self.intrusion_start_time = None # 💡 정상 인식 시 타이머 리셋
            elif max_val < 0.20:
                self._trigger_intrusion_timer()
            else:
                pass
        except Exception as e:
            print(f"[경고] OpenCV 유사도 분석 오류: {e}")
        finally:
            self.is_recognizing = False

    def _apply_ema_smoothing(self, new_bboxes):
            # BBox가 부드럽게 움직이도록 좌표 스무딩(EMA) 적용
            # 감지된 얼굴이 없으면 초기화
            if not new_bboxes:
                self.current_bboxes = []
                return
                
            # 처음 얼굴이 인식되었거나, 화면 속 얼굴 개수가 달라졌을 때 (예: 1명 -> 2명)
            if not self.current_bboxes or len(self.current_bboxes) != len(new_bboxes):
                self.current_bboxes = new_bboxes
                return

            alpha = 0.7 # 텐션 조절 (낮을수록 부드러움)
            smoothed = []
            for old_box, new_box in zip(self.current_bboxes, new_bboxes):
                ox, oy, ow, oh = old_box
                nx, ny, nw, nh = new_box
                
                # 이전 좌표와 현재 좌표를 부드럽게 믹스
                sx = int(ox * (1 - alpha) + nx * alpha)
                sy = int(oy * (1 - alpha) + ny * alpha)
                sw = int(ow * (1 - alpha) + nw * alpha)
                sh = int(oh * (1 - alpha) + nh * alpha)
                smoothed.append((sx, sy, sw, sh))
                
            self.current_bboxes = smoothed

    def _trigger_intrusion_timer(self):
            # [추가] 3초 유예 타이머 통합 관리
            if self.intrusion_start_time is None:
                self.intrusion_start_time = time.time()
                print("[AI] ⚠️ 수상한 움직임 감지! 1.5초 카운트다운 시작...")
            elif time.time() - self.intrusion_start_time > 1.5:
                self.status = "INTRUSION"
                print("[AI] 🚨 1.5초 초과! 머글 침입 감지 격발!")

"""