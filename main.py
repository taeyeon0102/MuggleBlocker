import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 우리가 분리해서 만든 기능 모듈 임포트
from ui.app_window import AppWindow
from pipeline.video_stream import VideoStreamer

import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import threading
import time
class MuggleBlockerApp:
    def __init__(self, root):
        self.root = root
        self.is_running = False
        self.streamer = None
        
        # UI 객체 생성 시, 버튼 클릭 시 실행할 콜백 함수를 넘겨줌
        self.ui = AppWindow(self.root, self.start_security, self.stop_security)
        
    def start_security(self):
        if not self.is_running:
            self.is_running = True
            self.ui.update_status("보안 감시 중...", "green", tk.DISABLED, tk.NORMAL)
            
            # UI가 멈추지 않도록 영상 스트리밍은 별도 스레드에서 실행
            self.thread = threading.Thread(target=self.video_loop, daemon=True)
            self.thread.start()

    def stop_security(self):
        if self.is_running:
            self.is_running = False
            self.ui.update_status("시스템 정지됨", "red", tk.NORMAL, tk.DISABLED)
            if self.streamer:
                self.streamer.release()
            self.ui.video_label.config(image='')

    def video_loop(self):
        self.streamer = VideoStreamer(0) # 웹캠 오픈
        
        if not self.streamer.is_opened:
            messagebox.showerror("카메라 오류", "웹캠을 열 수 없습니다.")
            self.root.after(0, self.stop_security)
            return

        while self.is_running:
            ret, rgb_frame = self.streamer.get_frame()
            if not ret:
                break
            
            # 1. 크기 조정 및 변환
            resized = cv2.resize(rgb_frame, (640, 360)) if 'cv2' in globals() else rgb_frame
            # (cv2 임포트가 안 빌트인 되어 있다면 변환을 위해 상단 혹은 내부에 import cv2 추가 가능)
            import cv2 
            resized = cv2.resize(rgb_frame, (640, 360))

            pil_img = Image.fromarray(resized)
            img_tk = ImageTk.PhotoImage(image=pil_img)
            
            # 2. UI 화면 업데이트
            if self.is_running:
                self.ui.video_label.config(image=img_tk)
                self.ui.video_label.image = img_tk
                
            time.sleep(0.03) # 배터리 최적화용 미세 대기 (약 30 FPS)

        if self.streamer:
            self.streamer.release()

    def on_closing(self):
        self.is_running = False
        if self.streamer:
            self.streamer.release()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = MuggleBlockerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()