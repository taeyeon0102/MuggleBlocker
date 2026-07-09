import tkinter as tk

class AppWindow:
    def __init__(self, window, start_callback, stop_callback):
        self.window = window
        self.window.title("Muggle Blocker - UI")
        self.window.geometry("700x550")
        
        self.start_callback = start_callback
        self.stop_callback = stop_callback
        
        self.create_widgets()

    def create_widgets(self):
        # 타이틀
        self.title_label = tk.Label(self.window, text="Muggle Blocker 시스템", font=("Helvetica", 16, "bold"))
        self.title_label.pack(pady=10)
        
        self.status_label = tk.Label(self.window, text="시스템 정지됨", fg="red", font=("Helvetica", 12))
        self.status_label.pack(pady=5)
        
        # 캠 화면 영역
        self.video_label = tk.Label(self.window, width=640, height=360, bg="black")
        self.video_label.pack(pady=10)
        
        # 제어 버튼
        self.btn_frame = tk.Frame(self.window)
        self.btn_frame.pack(pady=15)
        
        self.start_btn = tk.Button(self.btn_frame, text="보안 시작", width=15, height=2, bg="green", fg="white", command=self.start_callback)
        self.start_btn.grid(row=0, column=0, padx=10)
        
        self.stop_btn = tk.Button(self.btn_frame, text="보안 중지", width=15, height=2, bg="gray", fg="white", command=self.stop_callback, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=1, padx=10)

    def update_status(self, text, color, start_state, stop_state):
        """상태 레이블 및 버튼 활성화 상태 업데이트"""
        self.status_label.config(text=text, fg=color)
        self.start_btn.config(state=start_state)
        self.stop_btn.config(state=stop_state)