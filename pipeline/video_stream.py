import cv2

class VideoStreamer:
    def __init__(self, src=0):
        self.cap = cv2.VideoCapture(src)
        self.is_opened = self.cap.isOpened()

    def get_frame(self):
        """웹캠에서 프레임을 읽어오고 BGR을 RGB로 변환하여 반환"""
        if self.is_opened:
            ret, frame = self.cap.read()
            if ret:
                # Tkinter 표시를 위해 RGB로 변환하여 리턴
                return ret, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return False, None

    def release(self):
        """웹캠 자원 해제"""
        if self.is_opened:
            self.cap.release()