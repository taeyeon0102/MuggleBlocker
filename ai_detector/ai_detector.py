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
        """MediaPipe 비동기 콜백 함수: 분석 결과를 처리하여 상태값 갱신"""
        # 감지된 얼굴이 아예 없는 경우 -> AWAY
        if not result.detections:
            self.status = "AWAY"
            return

        # 비동기 분석 예약 시점에 보관해 두었던 오프셋 가져오기
        offsets = self.frame_offsets.pop(timestamp_ms, (0, 0, self.frame_width, self.frame_height))
        ox, oy, cw, ch = offsets

        for detection in result.detections:
            bbox = detection.bounding_box
            # 프레임 내 상대 좌표를 절대 픽셀 좌표로 환산
            x = max(0, ox + bbox.origin_x)
            y = max(0, oy + bbox.origin_y)
            w = min(cw, bbox.width)
            h = min(ch, bbox.height)

            # 얼굴 원본 이미지 슬라이싱 및 대조 연산 실행
            if self.user_encoding is not None and not self.is_recognizing:
                pass

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

    def process_frame(self, frame_rgb, timestamp_ms):
        """실시간 프레임을 주입받아 얼굴 분석 예약을 수행하는 함수"""
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
        """UI 루프에서 주기적으로 상태값('NORMAL', 'AWAY', 'INTRUSION')을 수거하는 함수"""
        return self.status

    # ==========================================================
    # 백그라운드 연산 스레드 메서드 영역
    # ==========================================================
    
    def _dlib_verify_identity_thread(self, frame_rgb):
        """[엔진 A] dlib 백그라운드 신원 대조 알고리즘"""
        try:
            # 1. dlib 감지기로 이미지 내 모든 얼굴 좌표 파악
            face_locations = face_recognition.face_locations(frame_rgb)

            # [1 단계] 얼굴이 아예 없을 때 -> AWAY
            if not face_locations:
                self.status = "AWAY"
                return
            
            # [2 단계] 얼굴이 2개 이상일 때 -> 무조건 INTRUSION 차단!
            if len(face_locations) >= 2:
                self.status = "INTRUSION"
                print(f"[AI] 🚨 화면에 {len(face_locations)}명 감지됨! (어깨너머 훔쳐보기 방어 격발!)")
                return

            # [3단계] 감지된 첫 번째 얼굴의 인코딩 백터 추출
            encodings = face_recognition.face_encodings(frame_rgb, face_locations)
            if self.user_encoding is not None and encodings:
                # 3. 등록된 주인(self.user_encoding)의 벡터와 현재 검출된 얼굴 벡터 1:1 비교
                # tolerance가 낮을수록 엄격하게 검증합니다. (보통 0.45 ~ 0.5가 적당합니다)
                matches = face_recognition.compare_faces([self.user_encoding], encodings[0], tolerance=0.45)
                
                if matches[0]:
                    self.status = "NORMAL"
                    print("[AI] dlib 기반 사용자 본인 확인 완료")
                else:
                    self.status = "INTRUSION"
                    print("[AI] dlib 기반 머글 침입 감지 격발!")
        except Exception as e:
            print(f"[경고] dlib 대조 중 에러: {e}")

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
                self.status = "NORMAL"
            elif max_val < 0.20:
                self.status = "INTRUSION"
                print("[AI] 머글 감지 격발!")
            else:
                pass
        except Exception as e:
            print(f"[경고] OpenCV 유사도 분석 오류: {e}")
        finally:
            self.is_recognizing = False