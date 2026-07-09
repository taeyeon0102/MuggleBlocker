import mediapipe as mp
import face_recognition
import time
import cv2
import math
import numpy as np
import threading

## 변수 할당
BaseOptions = mp.tasks.BaseOptions
FaceDetector = mp.tasks.vision.FaceDetector
FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions
FaceDetectorResult = mp.tasks.vision.FaceDetectorResult
VisionRunningMode = mp.tasks.vision.RunningMode

class MuggleBlockerDetector:
    # 초기화
    def __init__(self, model_path = '/Users/taeyeonkim/Desktop/coding/Python_Workspace/MuggleBlocker/blaze_face_short_range.tflite'):
        # 비율 계산시 필요한 변수
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
        self.recognition_interval = 5.0  # 시간 지정, 60초 기본
        self.is_stranger_detected = False
        self.is_recognizing = False


        # 사용자 얼굴 등록
        self.user_face_image = None # 웹캠에서 받아오기
        self.user_encoding = None

        # 옵션 설정
        options = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=VisionRunningMode.LIVE_STREAM,
            result_callback=self._save_result_callback,
            min_detection_confidence=0.5)
    
        self.detector = FaceDetector.create_from_options(options)

    # 사용자 얼굴 등록
    def register_user_face(self, frame_rgb) -> bool:

        encodings = face_recognition.face_encodings(frame_rgb)

        if len(encodings) > 0:
            self.user_encodings = encodings[0]
            return True
        else:
            return False


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


    # 1분 마다 사용자의 얼굴이 맞는지 검증
    def _verify_identity_thread(self, pure_crop_image):
        self.is_recognizing = True # 검증 시작 (락)
        try:

            self.user_encoding = face_recognition.face_encodings(self.user_face_image)[0]
            encodings = face_recognition.face_encodings(pure_crop_image)

            if len(encodings) > 0:
                match = face_recognition.compare_faces([self.user_encoding], encodings[0], tolerance=0.5)
                if not match[0]:
                    print("muggle detection!")
                    self.is_stranger_detected = True
                else:
                    print("normal 유지")
            else:
                print("크롭된 이미지를 찾지 못함")

        except Exception as e:
            print(f"🚨 얼굴 검증 스레드 에러 발생: {e}")
        finally:
            self.last_recognition_time = time.time() # 검문 시간 리셋
            self.is_recognizing = False # 검증 종료 (락 해제)

    # async detection
    def process_frame(self, frame, timestamp_ms: int):

        self.frame_count += 1 # 프레임 카운트 (3의 배수마다 실행)
        
        if frame is None:
            return
        
        # [최적화 1] 프레임 스킵 적용
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

        # 검증 트리거
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
  
    # bbox 반환
    def get_bbox(self):
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

        if self.is_stranger_detected:
            return "INTRUSION"

        # 응시 여부와 상관 없이 ROI 추적 박스 업데이트
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

        if staring_count == 0:
            self.muggle_detected_start_time = None
            if self.missed_frame_count < 30: # 30 프레임 연속으로 감지된 경우에만 away로 바꾸기(roi_box도 초기화)
                self.missed_frame_count += 1
                return "NORMAL"
            self.roi_box = None
            return "AWAY"
        
        elif staring_count == 1:
            ## face recognition 가져와서 판단 ## self.crop_box 이용하여 비교
            self.muggle_detected_start_time = None
            self.missed_frame_count = 0
            return "NORMAL"

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
        



# 테스트용
# 내 모듈 파일(ai_detector.py)을 직접 실행했을 때만 아래 코드가 돌아갑니다.
# (팀원이 import해서 쓸 때는 이 부분이 무시되어 아주 안전합니다.)


if __name__ == "__main__":
    print("=== 🧙‍♂️ 머글 블로커 AI 모듈 단독 테스트 시작 ===")
    
    detector = MuggleBlockerDetector()
    cap = cv2.VideoCapture(0)
    
    while cap.isOpened():
        success, frame = cap.read()
        if not success: 
            break
        
        # 1. AI 모듈에 프레임 전달
        timestamp_ms = int(time.time() * 1000)
        detector.process_frame(frame, timestamp_ms)
        
        # 2. 상태 및 좌표 가져오기
        current_status = detector.get_status()
        faces_bbox = detector.get_bbox()
        
        # 3. 화면 시각화 (디버깅)
        # 상태 텍스트 (AWAY: 노랑, NORMAL: 초록, INTRUSION: 빨강)
        color = (0, 255, 0)
        if current_status == "AWAY": color = (0, 255, 255)
        elif current_status == "INTRUSION": color = (0, 0, 255)
        
        cv2.putText(frame, f"Status: {current_status}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
        
        # 쳐다보는 사람 얼굴에 빨간 네모 그리기
        for box in faces_bbox:
            x, y, w, h = box
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
            cv2.putText(frame, "Staring", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            
        # ROI(최적화 영역)가 작동 중이면 파란 네모 그리기
        if detector.roi_box is not None:
            cropped_coords = detector.get_cropped_box()
            if cropped_coords is not None:         #반환된 값이 None이 아닐 때만 4개로 쪼개기 (안전장치)
                x1, x2, y1, y2 = cropped_coords
                
                # 파란색 네모 및 텍스트 그리기
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                cv2.putText(frame, "ROI Tracking", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
        
        # 화면 출력
        cv2.imshow('Muggle Blocker Test', frame) 
        if cv2.waitKey(1) & 0xFF == 27: # ESC 키
            break
            
    cap.release()
    cv2.destroyAllWindows()