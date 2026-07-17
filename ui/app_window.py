import tkinter as tk
import time
from PIL import Image, ImageTk
from pipeline.video_stream import VideoStreamer
from SystemController.SystemController import SystemController # 컨트롤러 임포트
from ai_detector.ai_detector import MuggleBlockerDetector # AI 디텍터 임포트

class AppWindow:
    def __init__(self, root):
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

        # 창 전체(root_all)에서 키가 눌릴 때와 뗄 때를 감지
        self.root.bind_all("<KeyPress>", self._tk_on_press)
        self.root.bind_all("<KeyRelease>", self._tk_on_release)
        
        # Canvas 내부 이미지 갱신용 객체 ID 저장 변수
        self.canvas_image_id = None
        self.photo = None # 이미지 객체가 가비지 컬렉터에 의해 사라지는 것을 방지

        # 캔버스 크기 및 상태 저장
        self.canvas_w = 960
        self.canvas_h = 540
        self.current_state = "NORMAL"

        # 에셋 로드 (기획안 명세 기준)
        try:
            self.fake_bg = Image.open("Assets/fake_desktop_wallpaper.png").resize((self.canvas_w, self.canvas_h))
            self.fake_photo = ImageTk.PhotoImage(self.fake_bg)
        except Exception:
            self.fake_photo = None
            print("[경고] 위장 배경 이미지(fake_desktop_wallpaper.png)를 찾을 수 없습니다.")

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
            self.canvas_image_id = None
            self.user_registered = False # 본인 등록 플래그 리셋
            
    def update_frame(self):
        """메인 비디오 프레임 갱신 및 AI 분석 피드백 루프"""
        if not self.is_running:
            return
        
        # [연결] 카메라에서 프레임 가져오기 (매번 가져와야 AI도 주고 화면도 그림)
        # AI가 헷갈리지 않게 오버레이 없는 깨끗한 원본(intrusion_mode=False)을 가져오기
        ret, frame_rgb = self.streamer.get_frame(intrusion_mode=False)

        if not ret or frame_rgb is None:
            self.loop_id = self.root.after(30, self.update_frame)
            return
        
        # [연결] 프로그램 켜자마자 웹캠 앞의 주인 얼굴을 최초 1회 자동 등록!
        if self.detector is not None and not self.user_registered:
            print("[시스템] 첫 화면에서 주인 얼굴을 탐색합니다...")
            if self.detector.register_user_face(frame_rgb):
                self.user_registered = True
                print("[시스템] 🧙‍♂️ 주인 얼굴 등록 완료! 본격 감시 시작!")
            else:
                pass # 첫 화면에서 얼굴을 못 찾았으면 0.03초 뒤에 다시 시도
            
        # AI 디텍터 상태 피드백 확인 (None 체크 및 안전장치)
        if self.detector is not None and self.user_registered:
            self._analyze_frame(frame_rgb)
            self.current_status = self.detector.get_status()

        if not self.controller.is_locked:
                # 1. 방어막이 꺼져있을 때(안 잠김) 머글이 나타나면 -> 잠근다!
                if self.current_status in ["INTRUSION", "AWAY"]:
                    print(f"[시스템] 🚨 {self.current_status} 감지! -> 보안 잠금 실행!")
                    self._trigger_system_lock()
                else:
                    # 2. 이미 방어막이 켜져있다면(잠김) -> AI가 NORMAL이라 해도 무시한다!
                    # (잠금 해제는 SystemController의 단축키가 알아서 처리하게 둡니다)
                    pass

        # 1. 컨트롤러 가동 상태(is_locked) 체크
        if self.controller.is_locked:
            # [상태 1] 잠금 상태인 경우: 화면에 위장 배경(바탕화면)을 렌더링
            self.status_label.config(text="보안 잠금 활성화 (Mischief Managed)", fg="darkred")
            if self.fake_photo:
                # 메모리에 오브젝트를 쌓지 않고 캔버스 이미지를 계속 교체하는 최적화 기법 적용
                if self.canvas_image_id is None:
                    self.canvas_image_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.fake_photo)
                else:
                    self.canvas.itemconfig(self.canvas_image_id, image=self.fake_photo)
            else:
                self.canvas.delete("all")
                self.canvas_image_id = None
                self.canvas.create_text(320, 180, text="Mischief Managed", fill="red", font=("Helvetica", 18))
            

        else:
            # 정상 감시 상태인 경우: 웹캠 프레임 정상 출력
            self.status_label.config(text="보안 감시 중...", fg="green")

            # BGR -> RGB 및 ImageTk 변환
            img = Image.fromarray(frame_rgb)
            img = img.resize((self.canvas_w, self.canvas_h)) # 카메라 크기 줄이기
            self.photo = ImageTk.PhotoImage(image=img)
            
            if self.canvas_image_id is None:
                self.canvas_image_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
            else:
                self.canvas.itemconfig(self.canvas_image_id, image=self.photo)
            
        # 약 30 FPS 속도로 갱신 주기 작동
        self.loop_id = self.root.after(30, self.update_frame)

    def _analyze_frame(self, frame_rgb):
        """프레임을 가공하여 AI 디텍터에게 분석을 예약하는 공통 처리 모듈"""
        if self.detector is not None:
            timestamp_ms = int(time.time() * 1000)
            self.detector.process_frame(frame_rgb, timestamp_ms)

    def _trigger_system_lock(self):
        """컨트롤러의 메서드 형태에 무관하게 안전하게 잠금을 실행하는 안전 트리거 함수"""
        try:
            if hasattr(self.controller, "lock_screen"):
                self.controller.lock_screen()
            else:
                self.controller.is_locked = True # 만약을 대비한 예외 처리

            # ⭐️ [핵심] 잠기는 순간 Tkinter 창이 키보드 이벤트를 무조건 받도록 포커스 강제 강탈!
            self.root.focus_force()
            self.root.lift() # 창을 맨 위로 띄우기

        except Exception as e:
            print(f"[경고] 시스템 컨트롤러 물리 잠금 격발 실패: {e}")

    def _trigger_system_unlock(self):
        """잠금을 실행한 것과 대칭되게 안전하게 잠금을 해제(Unlock)하는 안전 트리거 함수"""
        try:
            # 단축키를 안 눌렀더라도, AI가 주인을 알아봤다면 리스너를 꺼줘야 함
            if hasattr(self.controller, "unlock_screen"):
                self.controller.unlock_screen()
            else:
                self.controller.is_locked = False
        except Exception as e:
            print(f"[경고] 시스템 컨트롤러 잠금 해제 실패: {e}")

    def _tk_on_press(self, event):
        """키가 눌렸을 때 실행 (맥/윈도우 호환 키 트래커)"""
        # 소문자로 변환하여 알파벳 및 키 이름 저장
        self.pressed_keys.add(event.keysym.lower())
        
        # 1. Ctrl 키가 눌려있는지 확인 ('control'이 포함된 모든 키 심볼 대응)
        has_ctrl = any('control' in k for k in self.pressed_keys)
        
        # 2. Shift 키가 눌려있는지 확인 ('shift'가 포함된 모든 키 심볼 대응)
        has_shift = any('shift' in k for k in self.pressed_keys)
        
        # 3. 'm' 키가 눌려있는지 확인
        has_m = 'm' in self.pressed_keys

        # 세 키가 동시에 눌렸고, 현재 화면이 잠겨있는 상태라면?
        if has_ctrl and has_shift and has_m:
            if self.controller.is_locked:
                print("[시스템] 비밀 단축키 입력 감지! 잠금을 해제합니다.")
                self.controller.unlock_screen()

    def _tk_on_release(self, event):
        """키에서 손을 텄을 때 실행"""
        keysym = event.keysym.lower()
        if keysym in self.pressed_keys:
            self.pressed_keys.remove(keysym)