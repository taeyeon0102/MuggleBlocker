import tkinter as tk
import time
import os # 애플스크립트 이용, 프로세스 종료 등
import platform # 운영체제 알아내기
from PIL import Image, ImageTk
from pipeline.video_stream import VideoStreamer
from SystemController.SystemController import SystemController # 컨트롤러 임포트
from ai_detector.ai_detector import MuggleBlockerDetector # AI 디텍터 임포트

# ⭐️ 추후 이펙트 파일을 만드시면 아래 주석을 풀고 사용하세요!
# from ui.effects.intrusion_effect import play_intrusion_sequence
from ui.effects.away_effect import play_away_sequence

class AppWindow:
    def __init__(self, root): # ⭐️ main.py 에러 방지 (root만 남김)
        self.root = root
        self.root.title("Muggle Blocker - UI")
        
        # [수정] 맥북 전체 화면 덮기 & 모니터 해상도 자동 계산!
        self.root.geometry("1024x768")
        
        # 1. AI 디텍터, 시스템 컨트롤러 및 비디오 스트리머 초기화
        try:
            self.detector = MuggleBlockerDetector()
        except Exception as e:
            print(f"[오류] AI 감지 모듈 초기화 실패: {e}")
            self.detector = None

        self.controller = SystemController()
        self.streamer = VideoStreamer()
        self.is_running = False  # 시작 버튼 제어용 플래그
        self.loop_id = None      # tkinter after 예약 취소용 ID
        self.user_registered = False # 본인 신원 등록 완료 여부 플래그
        self.pressed_keys = set() # 단축키 검사 세트 (실시간 추적)

        # [추가] 내 노트북 모니터의 전체 가로, 세로 픽셀 사이즈를 자동 측정해서 저장
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()

        # 창 전체(root_all)에서 키가 눌릴 때와 뗄 때를 감지
        self.root.bind_all("<KeyPress>", self._tk_on_press)
        self.root.bind_all("<KeyRelease>", self._tk_on_release)
        
        # Canvas 내부 이미지 갱신용 객체 ID 저장 변수
        self.canvas_image_id = None
        self.photo = None # 이미지 객체가 가비지 컬렉터에 의해 사라지는 것을 방지

        # 캔버스 크기 및 상태 저장
        self.canvas_w = 960
        self.canvas_h = 540
        self.current_status = "NORMAL"

        # 에셋 로드 (기획안 명세 기준)
        try:
            self.fake_bg = Image.open("Assets/fake_desktop_wallpaper.png").resize((self.canvas_w, self.canvas_h))
            self.fake_photo = ImageTk.PhotoImage(self.fake_bg)
            
            # ⭐️ [추가] 모니터 전체를 덮을 거대한 풀스크린 이미지 (이펙트용)
            self.fake_bg_full = Image.open("Assets/fake_desktop_wallpaper.png").resize((self.screen_w, self.screen_h))
            self.fake_photo_full = ImageTk.PhotoImage(self.fake_bg_full)
        except Exception:
            self.fake_photo = None
            self.fake_photo_full = None
            print("[경고] 위장 배경 이미지를 찾을 수 없습니다.")

        # 1. UI 헤더 영역
        self.title_label = tk.Label(root, text="Muggle Blocker 시스템", font=("Helvetica", 16, "bold"))
        self.title_label.pack(pady=10)
        
        self.status_label = tk.Label(root, text="시스템 정지됨", fg="red", font=("Helvetica", 12))
        self.status_label.pack(pady=5)

        self.canvas = tk.Canvas(root, width=self.canvas_w, height=self.canvas_h, bg="black")
        self.canvas.pack(pady=10)
        
        # 3. 제어 버튼 하단 배치
        self.btn_toggle = tk.Button(root, text="방어막 켜기 (ON)", command=self.toggle_system, font=("Helvetica", 11))
        self.btn_toggle.pack(pady=10)
        
        # ⭐️ [추가] "X" 버튼 클릭 시 찌꺼기(웹캠 스레드) 없이 안전하게 자폭하도록 연결
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def toggle_system(self):
        """방어막 ON/OFF 전환 버튼 제어 함수"""
        if not self.is_running:
            self.is_running = True
            self.status_label.config(text="보안 감시 중...", fg="green")
            self.btn_toggle.config(text="방어막 끄기 (OFF)")
            self.update_frame()
        else:
            self.is_running = False
            self.status_label.config(text="시스템 정지됨", fg="red")
            self.btn_toggle.config(text="방어막 켜기 (ON)")
            self.canvas.delete("all")
            self.canvas_image_id = None
            self.user_registered = False # 본인 등록 플래그 리셋
            
    def update_frame(self):
        """메인 비디오 프레임 갱신 및 AI 분석 피드백 루프"""
        if not self.is_running:
            return
        
        ret, frame_rgb = self.streamer.get_frame(intrusion_mode=False)

        if not ret or frame_rgb is None:
            self.loop_id = self.root.after(30, self.update_frame)
            return
        
        # 프로그램 켜자마자 웹캠 앞의 주인 얼굴을 최초 1회 자동 등록!
        if self.detector is not None and not self.user_registered:
            print("[시스템] 첫 화면에서 주인 얼굴을 탐색합니다...")
            if self.detector.register_user_face(frame_rgb):
                self.user_registered = True
                print("[시스템] 🧙‍♂️ 주인 얼굴 등록 완료! 본격 감시 시작!")
            else:
                pass
            
        # AI 디텍터 상태 피드백 확인
        if self.detector is not None and self.user_registered:
            self._analyze_frame(frame_rgb)
            self.current_status = self.detector.get_status()

        if not self.controller.is_locked:
            # 1. 방어막이 꺼져있을 때(안 잠김) 머글이 나타나면 -> 잠근다!
            if self.current_status in ["INTRUSION", "AWAY"]:
                print(f"[시스템] 🚨 {self.current_status} 감지! -> 보안 잠금 실행!")
                self._trigger_system_lock()

        # 1. 컨트롤러 가동 상태(is_locked) 체크
        if self.controller.is_locked:
            self.status_label.config(text="보안 잠금 활성화 (Mischief Managed)", fg="darkred")
            if self.fake_photo:
                if self.canvas_image_id is None:
                    self.canvas_image_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.fake_photo)
                else:
                    self.canvas.itemconfig(self.canvas_image_id, image=self.fake_photo)
            else:
                self.canvas.delete("all")
                self.canvas_image_id = None
                self.canvas.create_text(320, 180, text="Mischief Managed", fill="red", font=("Helvetica", 18))
            
        else:
            self.status_label.config(text="보안 감시 중...", fg="green")
            img = Image.fromarray(frame_rgb)
            img = img.resize((self.canvas_w, self.canvas_h))
            self.photo = ImageTk.PhotoImage(image=img)
            
            if self.canvas_image_id is None:
                self.canvas_image_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
            else:
                self.canvas.itemconfig(self.canvas_image_id, image=self.photo)
            
        self.loop_id = self.root.after(30, self.update_frame)

    def _analyze_frame(self, frame_rgb):
        if self.detector is not None:
            timestamp_ms = int(time.time() * 1000)
            self.detector.process_frame(frame_rgb, timestamp_ms)

    def _trigger_system_lock(self):
        """컨트롤러의 메서드 형태에 무관하게 안전하게 잠금을 실행하는 안전 트리거 함수"""
        try:
            if hasattr(self.controller, "lock_screen"):
                self.controller.lock_screen()
            else:
                self.controller.is_locked = True 

            current_os = platform.system()

            if current_os == "Darwin": 
                pid = os.getpid()
                os.system(f"osascript -e 'tell application \"System Events\" to set frontmost of the first process whose unix id is {pid} to true'")
            elif current_os == "Windows":
                self.root.overrideredirect(True)

            # 1. 화면 띄우고 덮기
            self.root.deiconify() 
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.geometry(f"{self.screen_w}x{self.screen_h}+0+0")
            self.root.after(500, self.root.focus_force) 

            if current_os == "Windows":
                self.root.after(500, self.root.grab_set)

            # 2. 상태에 맞는 외부 이펙트 시퀀스 호출
            if self.current_status == "INTRUSION":
                # 외부 함수에 UI 제어권(self)을 넘겨서 애니메이션 실행
                # play_intrusion_sequence(self) 
                pass
            elif self.current_status == "AWAY":
                    play_away_sequence(self)
                    pass
            else:
                pass
            
            # 3. 화면 넘어가는 동안 눌려있던 키보드 캐시 초기화
            if hasattr(self, 'pressed_keys'):
                self.pressed_keys.clear()

        except Exception as e:
            print(f"[경고] 시스템 컨트롤러 물리 잠금 격발 실패: {e}")

    def _trigger_system_unlock(self):
        """잠금을 실행한 것과 대칭되게 안전하게 잠금을 해제하는 함수"""
        try:
            if hasattr(self.controller, "unlock_screen"):
                self.controller.unlock_screen()
            else:
                self.controller.is_locked = False

            current_os = platform.system()

            if current_os == "Windows":
                self.root.grab_release()
                self.root.overrideredirect(False)      

            self.root.attributes("-topmost", False)
            self.root.geometry("1024x768")         

            # 4. 팀원분이 그려둔 외부 이펙트(캔버스) 싹 치우기
            if hasattr(self, 'effect_canvas') and self.effect_canvas:
                self.effect_canvas.place_forget()
                self.effect_canvas = None # 메모리 정리

        except Exception as e:
            print(f"[경고] 시스템 컨트롤러 잠금 해제 실패: {e}")

    def _tk_on_press(self, event):
        self.pressed_keys.add(event.keysym.lower())
        has_ctrl = any('control' in k for k in self.pressed_keys)
        has_shift = any('shift' in k for k in self.pressed_keys)
        has_m = 'm' in self.pressed_keys

        if has_ctrl and has_shift and has_m:
            if self.controller.is_locked:
                print("[시스템] 비밀 단축키 입력 감지! 잠금을 해제합니다.")
                self._trigger_system_unlock()

    def _tk_on_release(self, event):
        keysym = event.keysym.lower()
        if keysym in self.pressed_keys:
            self.pressed_keys.remove(keysym)

    def on_closing(self):
        """[시스템] 윈도우 종료 이벤트 핸들러: 프로그램 완전 자폭 (좀비 프로세스 방지)"""
        print("[시스템] 프로그램을 안전하게 종료합니다...")
        self.is_running = False 
        
        if hasattr(self, 'streamer') and self.streamer:
            try:
                self.streamer.stop() 
            except:
                pass
                
        self.root.destroy()
        os._exit(0) # 완벽한 백그라운드 킬