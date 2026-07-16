import tkinter as tk
from PIL import Image, ImageTk
from pipeline.video_stream import VideoStreamer
from SystemController.SystemController import SystemController # 컨트롤러 임포트

class AppWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("Muggle Blocker - UI")
        self.root.geometry("700x550")
        
        # 시스템 컨트롤러 및 비디오 스트리머 초기화
        self.controller = SystemController()
        self.streamer = VideoStreamer()
        self.is_running = False  # 시작 버튼 제어용 플래그
        
        # 에셋 로드 (기획안 명세 기준)
        try:
            self.fake_bg = Image.open("Assets/fake_desktop_wallpaper.png").resize((640, 360))
            self.fake_photo = ImageTk.PhotoImage(self.fake_bg)
        except Exception:
            self.fake_photo = None
            print("[경고] 위장 배경 이미지(fake_desktop_wallpaper.png)를 찾을 수 없습니다.")

        # 1. UI 헤더 영역
        self.title_label = tk.Label(root, text="Muggle Blocker 시스템", font=("Helvetica", 16, "bold"))
        self.title_label.pack(pady=10)
        
        self.status_label = tk.Label(root, text="시스템 정지됨", fg="red", font=("Helvetica", 12))
        self.status_label.pack(pady=5)
        
        # 2. 비디오 캔버스 영역 (640x360 규격)
        self.canvas = tk.Canvas(root, width=640, height=360, bg="black")
        self.canvas.pack(pady=10)
        
        # 3. 제어 버튼 하단 배치
        self.btn_toggle = tk.Button(root, text="방어막 켜기 (ON)", command=self.toggle_system, font=("Helvetica", 11))
        self.btn_toggle.pack(pady=10)
        
    def toggle_system(self):
        """방어막 ON/OFF 전환 버튼 제어 함수"""
        if not self.is_running:
            self.is_running = True
            self.status_label.config(text="보안 감시 중...", fg="green")
            self.btn_toggle.config(text="방어막 끄기 (OFF)")
            # self.streamer.start() # 비디오 캡처 스레드 가동
            self.update_frame()
        else:
            self.is_running = False
            self.status_label.config(text="시스템 정지됨", fg="red")
            self.btn_toggle.config(text="방어막 켜기 (ON)")
            # self.streamer.stop() # 비디오 캡처 스레드 정지
            self.canvas.delete("all")
            
    def update_frame(self):
        """메인 비디오 프레임 갱신 루프"""
        if not self.is_running:
            return
            
        # 1. 컨트롤러 가동 상태(is_locked) 체크
        if self.controller.is_locked:
            # 잠금 상태인 경우: 화면 위장 배경을 캔버스에 렌더링
            self.status_label.config(text="보안 잠금 활성화 (Mischief Managed)", fg="darkred")
            if self.fake_photo:
                self.canvas.create_image(0, 0, anchor=tk.NW, image=self.fake_photo)
            else:
                self.canvas.delete("all")
                self.canvas.create_text(320, 180, text="Mischief Managed", fill="red", font=("Helvetica", 18))
        else:
            # 정상 감시 상태인 경우: 웹캠 프레임 정상 출력
            self.status_label.config(text="보안 감시 중...", fg="green")
            ret, frame = self.streamer.get_frame()
            if ret and frame is not None:
                # BGR -> RGB 및 ImageTk 변환
                img = Image.fromarray(frame)
                self.photo = ImageTk.PhotoImage(image=img)
                self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
                
        # 약 30 FPS 주기 주기로 부드럽게 루프 재귀 호출 (0.03초)
        self.root.after(30, self.update_frame)