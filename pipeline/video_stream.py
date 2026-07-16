import cv2
import os

class VideoStreamer:
    def __init__(self, src=0):
        self.cap = cv2.VideoCapture(src)
        self.is_opened = self.cap.isOpened()
        
        # 디멘터 성에(Frost) 에셋 로드 설정
        self.assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Assets")
        self.overlay_path = os.path.join(self.assets_dir, "intrusion_frost_overlay.png")
        self.frost_img = None
        
        if os.path.exists(self.overlay_path):
            self.frost_img = cv2.imread(self.overlay_path)
        else:
            print(f"[경고] 성에 오버레이 에셋을 찾을 수 없습니다: {self.overlay_path}")

    def get_frame(self, intrusion_mode=False):
        """웹캠에서 프레임을 읽어오고 BGR을 RGB로 변환하여 반환.
        intrusion_mode가 True일 경우 디멘터 성에 오버레이를 화면에 합성합니다.
        """
        if self.is_opened:
            ret, frame = self.cap.read()
            if ret:
                # 1. 침입 감지 모드(Repello Muggletum) 활성화 시 성에 오버레이 합성
                if intrusion_mode and self.frost_img is not None:
                    h, w, _ = frame.shape
                    resized_frost = cv2.resize(self.frost_img, (w, h))
                    
                    # 기획안 가이드에 따른 cv2.addWeighted 오버레이 합성 (원본 60%, 얼음 효과 40%)
                    frame = cv2.addWeighted(frame, 0.6, resized_frost, 0.4, 0)
                
                # 2. Tkinter 표시 및 AI 검출을 위해 BGR을 RGB로 변환하여 리턴
                return ret, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
        return False, None

    def release(self):
        """웹캠 자원 해제"""
        if self.is_opened:
            self.cap.release()