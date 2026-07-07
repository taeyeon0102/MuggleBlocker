import mediapipe as mp
import time
import os
import cv2

## 변수 할당
BaseOptions = mp.tasks.BaseOptions
FaceDetector = mp.tasks.vision.FaceDetector
FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions
FaceDetectorResult = mp.tasks.vision.FaceDetectorResult
VisionRunningMode = mp.tasks.vision.RunningMode

class MuggleBlockerDetector:
    # 초기화
    def __init__(self, model_path = '/Users/taeyeonkim/Desktop/coding/Python_Workspace/MuggleBlocker/blaze_face_short_range.tflite'):
        # 비동기식 콜백에서 받은 변수 저장소
        self.latest_result = None

        # 옵션 설정
        options = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=VisionRunningMode.LIVE_STREAM,
            result_callback=self._save_result_callback,
            min_detection_confidence=0.5)
    
        self.detector = FaceDetector.create_from_options(options)

    # call back
    def _save_result_callback(self, result, output_image: mp.Image, timestamp_ms: int):
        # MediaPipe가 얼굴 판별을 끝낼 때마다 백그라운드에서 자동으로 호출되는 함수
        # 결과만 클래스 변수에 저장함 (latest_result)
        self.latest_result = result

    # async detection
    def process_frame(self, frame, timestamp_ms: int):

        if frame is None:
            return
        
        # openCV는 BGR을 MediaPipe 전용 포맷으로 변경
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format = mp.ImageFormat.SRGB, data = frame_rgb)

        # 비동기 감지 실행 (결과는 백그라운드에서 _save_result로 들어옴)
        self.detector.detect_async(mp_image, timestamp_ms)


    # bbox point (for crop)
    def get_bbox(self) -> list:
        if not self.latest_result and not self.latext_result.detections:
            return []
        
        # 얼굴을 찾았다면 -> 좌표 반환
        boxes = []
        if self.latest_result and self.latest_result.detections:
            for detection in self.latest_result.detections:
                bbox = detection.bounding_box
                boxes.append(bbox.origin_x, bbox.origin_y, bbox.width, bbox.height)
        return boxes
    
    
    # status (반환값: 'NORMAL', 'AWAY', 'INSTRUSION')
    def get_status(self) -> str:
        if not self.latest_result and not self.latest_result.detections:
            return "AWAY"
        face_count = len(self.latest_result.detections)

        if face_count >= 2:
            return "INSTRUSION"
        
        # face_count=1 & 사용자 얼굴!
        return "NORMAL"