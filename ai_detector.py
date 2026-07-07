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
        # 비율 계산시 필요한 변수
        self.frame_width = 0
        self.frame_height = 0

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
        
        # 프레임 크기 갱신
        self.frame_height, self.frame_width, _ = frame.shape
        
        # openCV는 BGR을 MediaPipe 전용 포맷으로 변경
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format = mp.ImageFormat.SRGB, data = frame_rgb)

        # 비동기 감지 실행 (결과는 백그라운드에서 _save_result로 들어옴)
        self.detector.detect_async(mp_image, timestamp_ms)


    # bbox point (for crop & get_staring_face) : face_data_list 반환
    def _get_face_data_list(self) -> list:
        if not self.latest_result or not self.latest_result.detections:
            return []
        
        face_data_list = []
        for detection in self.latest_result.detections:
            # bbox point
            bbox = detection.bounding_box
            boxes = [bbox.origin_x, bbox.origin_y, bbox.width, bbox.height]
            # 6개 특징점 (좌표로 변환 후))
            keypoints = []
            if detection.keypoints:
                for keypoint in detection.keypoints:
                    keypoints.append((int(keypoint.x * self.frame_width), int(keypoint.y * self.frame_height)))
            # 묶어서 반환
            face_data_list.append({
                "boxes": boxes,
                "keypoints": keypoints
            })

        return face_data_list
    
    # 응시하는지 확인 (응시하는 얼굴 카운트)
    def _get_staring_faces(self):

        face_data_list = self._get_face_data_list()

        staring_faces = []

        for face in face_data_list:
            box = face["boxes"]
            kps = face["keypoints"]

            box_center_x = box[0] + box[2]/2 # 얼굴 중앙 x좌표
            nose_x = kps[2][0] # 코 끝 x좌표

            # 코가 중앙에서 얼마나 벗어났는지 비율 계산 (0.0 ~ 1.0)
            offset_ratio = abs(box_center_x - nose_x) / (box[2]/2)

            if offset_ratio < 0.4:
                print("응시 중...")
                staring_faces.append(face)
            else:
                print("그냥 지나가는 사람...")

        return staring_faces
  
    # bbox 반환
    def get_bbox(self):
        staring_faces = self._get_staring_faces()
        boxes = [face['boxes'] for face in staring_faces]
        return boxes
    
    # 화면을 응시 중인 얼굴을 걸러내서 status 판단 (반환값: 'NORMAL', 'AWAY', 'INSTRUSION')
    # 핵심 판별 부분
    def get_status(self) -> str:

        staring_faces = self._get_staring_faces()
        staring_count = len(staring_faces)

        if staring_count == 0:
            return "AWAY"
        elif staring_count >= 2:
            return "INTRUSION"
        elif staring_count == 1:
            ## 인식 함수 가져와서 판단 ##
            return "NORMAL"
        



# 내 모듈 파일(ai_detector.py)을 직접 실행했을 때만 아래 코드가 돌아갑니다.
# (팀원이 import해서 쓸 때는 이 부분이 무시되어 아주 안전합니다.)

if __name__ == "__main__":
    import cv2
    import time
    
    print("=== 머글 블로커 AI 모듈 단독 테스트 시작 ===")
    
    # 1. 내가 만든 클래스 객체 생성
    detector = MuggleBlockerDetector()
    
    # 2. 웹캠 켜기
    cap = cv2.VideoCapture(0)
    
    while cap.isOpened():
        success, frame = cap.read()
        if not success: break
        
        # 3. 내 모듈에 프레임 던져주기
        timestamp_ms = int(time.time() * 1000)
        detector.process_frame(frame, timestamp_ms)
        
        # 4. 내 모듈이 판별한 상태값 가져와서 콘솔에 출력하기!
        current_status = detector.get_status()
        print(f"현재 상태: {current_status}")
        
        # --- (여기서부터 추가) ---
        # 1. 상태 텍스트 화면에 찍기 (초록색 글씨)
        cv2.putText(frame, f"Status: {current_status}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
        
        # 2. 쳐다보는 사람 얼굴에 빨간 네모 그리기
        boxes = detector.get_bbox()
        for box in boxes:
            x, y, w, h = box
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
        # --- (여기까지 추가) ---
        
        # 화면 출력 (주의: 글씨가 뒤집혀 보일 수 있으니 flip은 뺐습니다!)
        cv2.imshow('Detector Test', frame) 
        if cv2.waitKey(1) & 0xFF == 27:
            break
            
    cap.release()
    cv2.destroyAllWindows()