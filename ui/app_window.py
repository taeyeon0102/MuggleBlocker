import tkinter as tk
import time
import os # 애플스크립트 이용, 프로세스 종료 등
import platform # 운영체제 알아내기

from PIL import Image, ImageTk, ImageGrab # 현재 화면 캡처
import numpy as np
import cv2

from pipeline.video_stream import VideoStreamer
from SystemController.SystemController import SystemController # 컨트롤러 임포트
from ai_detector.ai_detector import MuggleBlockerDetector # AI 디텍터 임포트
from ui.effects.intrusion_effect import play_intrusion_sequence
from ui.effects.away_effect import play_away_sequence

class AppWindow:
    def __init__(self, root): # ⭐️ main.py 에러 방지 (root만 남김)
        self.root = root
        self.root.title("Muggle Blocker - UI")
        
        # 맥북 전체 화면 덮기 & 모니터 해상도 자동 계산
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
        self.global_pressed_keys = set() # OS 백그라운드 단축키 수신 세트

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
            
            # [추가] 모니터 전체를 덮을 거대한 풀스크린 이미지 (이펙트용)
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
        
        # 2. 제어 버튼 하단 배치
        self.btn_toggle = tk.Button(root, text="방어막 켜기 (ON)", command=self.toggle_system, font=("Helvetica", 11))
        self.btn_toggle.pack(pady=10)
        
        # OS 레벨 글로벌 키보드 백그라운드 리스너 구동 (포커스 상태 무관 감지)
        self.pynput_listener = None # 맥을 위해 기본값은 None으로 설정
        # 운영체제가 '윈도우(Windows)'일 때만 pynput 라이브러리를 켜기!
        if platform.system() == "Windows":
            from pynput import keyboard # 윈도우에서만 임포트
            self.pynput_listener = keyboard.Listener(
                on_press=self._on_global_key_press,
                on_release=self._on_global_key_release
            )
            self.pynput_listener.daemon = True
            self.pynput_listener.start()
            print("[시스템] 🪟 Windows 환경 감지: 백그라운드 단축키 활성화")
        else:
            print("[시스템] 🍎 macOS 환경 감지: 백그라운드 단축키 비활성화 (Face-ID로 대체)")

        # "X" 버튼 클릭 시 찌꺼기(웹캠 스레드) 없이 안전하게 자폭하도록 연결
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _on_global_key_press(self, key):
        """pynput 백그라운드 스레드에서 수신되는 글로벌 KeyPress 이벤트"""
        try:
            if hasattr(key, 'char') and key.char:
                self.global_pressed_keys.add(key.char.lower())
            elif hasattr(key, 'name') and key.name:
                self.global_pressed_keys.add(key.name.lower())
            else:
                self.global_pressed_keys.add(str(key).lower())
        except Exception:
            pass

        has_ctrl = any(k in self.global_pressed_keys for k in ['ctrl', 'ctrl_l', 'ctrl_r', 'key.ctrl', 'key.ctrl_l', 'key.ctrl_r'])
        has_shift = any(k in self.global_pressed_keys for k in ['shift', 'shift_l', 'shift_r', 'key.shift', 'key.shift_l', 'key.shift_r'])
        has_m = 'm' in self.global_pressed_keys

        if has_ctrl and has_shift and has_m:
            is_canvas_active = hasattr(self, 'effect_canvas') and self.effect_canvas is not None
            if self.controller.is_locked or is_canvas_active:
                print("\n[시스템] 🔑 글로벌 비밀 단축키(Ctrl+Shift+M) 입력 감지! 잠금을 해제합니다.")
                self.global_pressed_keys.clear()
                self.root.after(0, self._trigger_system_unlock)

    def _on_global_key_release(self, key):
        """pynput 백그라운드 스레드에서 수신되는 글로벌 KeyRelease 이벤트"""
        try:
            if hasattr(key, 'char') and key.char:
                self.global_pressed_keys.discard(key.char.lower())
            elif hasattr(key, 'name') and key.name:
                self.global_pressed_keys.discard(key.name.lower())
            else:
                self.global_pressed_keys.discard(str(key).lower())
        except Exception:
            pass

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

        # 잠금 상태 및 외부 이펙트 캔버스 활성화 여부 확인
        is_effect_active = hasattr(self, 'effect_canvas') and self.effect_canvas is not None

        # ⭐️ [핵심 보완] 잠긴 상태에서는 확실히 NORMAL 상태 & 유사도 조건 만족할 때만 해제
        if (self.controller.is_locked or is_effect_active):
            detector_status = getattr(self.detector, 'status', '') if self.detector else ''
            
            # 디텍터 내부에 similarity 속성이 존재한다면 0.70 이상인지 이중 체크
            current_sim = getattr(self.detector, 'last_similarity', getattr(self.detector, 'similarity', 1.0))
            
            if self.current_status == "NORMAL" and detector_status == "NORMAL" and current_sim >= 0.70:
                print("[시스템] 🔓 주인 신원 인증 완료 (NORMAL) -> 보안 잠금을 해제합니다.")
                self._trigger_system_unlock()

        if not self.controller.is_locked and not is_effect_active:
            # 1. 방어막이 꺼져있을 때(안 잠김) 머글이나 부재(AWAY)가 나타나면 -> 잠근다!
            if self.current_status in ["INTRUSION", "AWAY"]:
                # 잠금을 푼 지 3초가 안 지났다면 다시 잠그지 않고 무시!
                if time.time() - getattr(self, 'last_unlock_time', 0) > 3.0:
                    print(f"[시스템] 🚨 {self.current_status} 감지! -> 보안 잠금 실행!")
                    self._trigger_system_lock()

        # 컨트롤러 가동 상태(is_locked) 체크
        if self.controller.is_locked or is_effect_active:
            self.status_label.config(text="보안 잠금 활성화 (Mischief Managed)", fg="darkred")
            if self.fake_photo_full:
                if self.canvas_image_id is None:
                    self.canvas_image_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.fake_photo_full)
                else:
                    self.canvas.itemconfig(self.canvas_image_id, image=self.fake_photo_full)
            else:
                self.canvas.delete("all")
                self.canvas_image_id = None
                self.canvas.create_text(self.screen_w//2, self.screen_h//2, text="Mischief Managed", fill="red", font=("Helvetica", 32))
            
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

            # Tkinter 창이 풀스크린으로 화면을 덮기 '직전'에 현재 바탕화면 캡처!
            try:
                # 모니터 해상도만큼 캡처 후 OpenCV(BGR) 포맷으로 변환
                screen_img = ImageGrab.grab(bbox=(0, 0, self.screen_w, self.screen_h))
                self.captured_desktop = cv2.cvtColor(np.array(screen_img), cv2.COLOR_RGB2BGR)
            except Exception as e:
                print(f"[경고] 화면 캡처 실패 (권한 문제 등): {e}")
                # 캡처 실패 시 검은 화면 대체
                self.captured_desktop = np.full((self.screen_h, self.screen_w, 3), 0, dtype=np.uint8)

            # 창 속성을 건드리기 전에, 캔버스를 '방금 캡처한 바탕화면'으로 즉시 덮어씌움
            cv2_im_rgb = cv2.cvtColor(self.captured_desktop, cv2.COLOR_BGR2RGB)
            self.photo = ImageTk.PhotoImage(image=Image.fromarray(cv2_im_rgb))
            if self.canvas_image_id is None:
                self.canvas_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
            else:
                self.canvas.itemconfig(self.canvas_image_id, image=self.photo)

            # 방해되는 기존 UI 요소들 숨기기
            self.title_label.pack_forget()
            self.status_label.pack_forget()
            self.btn_toggle.pack_forget()

            # 캔버스 크기를 풀스크린으로 강제 확장
            self.canvas.config(width=self.screen_w, height=self.screen_h)
            self.canvas.pack(fill="both", expand=True)

            self.root.update()

            # 풀스크린 상단 고정 처리
            current_os = platform.system()

            self.root.overrideredirect(True) 
            self.root.geometry(f"{self.screen_w}x{self.screen_h}+0+0")
            self.root.attributes("-topmost", True)
            self.root.lift()
            
            self.root.update()
            
            if current_os == "Darwin":
                pid = os.getpid()
                os.system(f"osascript -e 'tell application \"System Events\" to set frontmost of the first process whose unix id is {pid} to true'")
        
            # 최상단 창 및 캔버스로 포커스 강제 획득
            self.root.focus_force()
            self.canvas.focus_set()

            # 화면 아무 곳이나 마우스 클릭 시 즉시 키보드 포커스 재탈환
            self.root.bind_all("<Button-1>", lambda e: self.root.focus_force())

            # 상태에 맞는 외부 이펙트 시퀀스 호출
            if self.current_status == "INTRUSION":
                play_intrusion_sequence(self) 
            elif self.current_status == "AWAY":
                play_away_sequence(self)
            
            # 화면 넘어가는 동안 눌려있던 키보드 캐시 초기화
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

            # 잠금 해제 시 상태를 NORMAL로 재설정
            self.current_status = "NORMAL"
            if self.detector is not None and hasattr(self.detector, 'status'):
                self.detector.status = "NORMAL"

            current_os = platform.system()
            if current_os == "Darwin":
                self.root.overrideredirect(False)
                self.root.attributes("-fullscreen", False)
                self.root.update()
                time.sleep(0.1) # OS가 창을 줄일 시간을 아주 잠깐 줌
            elif current_os == "Windows":
                self.root.withdraw()
                self.root.grab_release()
                self.root.overrideredirect(False)
                self.root.deiconify()

            self.root.attributes("-topmost", False)
            self.root.geometry("1024x768")         

            # ⭐️ 화면을 덮고 있던 풀스크린 이펙트 캔버스(away/intrusion)를 완전히 파기하여 제거
            if hasattr(self, 'effect_canvas') and self.effect_canvas is not None:
                try:
                    self.effect_canvas.place_forget()
                    self.effect_canvas.destroy()
                except Exception:
                    pass
                self.effect_canvas = None

            # 캔버스 크기 원상 복구 및 UI 재배치
            self.canvas.pack_forget() # 패킹 순서 초기화를 위해 일단 제거
            self.canvas.config(width=self.canvas_w, height=self.canvas_h)
            
            # 기존 순서대로 다시 pack()
            self.title_label.pack(pady=10)
            self.status_label.pack(pady=5)
            self.canvas.pack(pady=10)
            self.btn_toggle.pack(pady=10)

            # 원래 UI로 깔끔하게 다시 표시
            self.root.update()

            # 해제 시에도 포커스를 잃지 않도록 강제
            if current_os == "Darwin":
                pid = os.getpid()
                os.system(f"osascript -e 'tell application \"System Events\" to set frontmost of the first process whose unix id is {pid} to true'")
            self.root.focus_force()

            # 꼬임 방지 및 쿨타임용 변수 세팅 (맨 마지막에 추가!)
            if hasattr(self, 'pressed_keys'):
                self.pressed_keys.clear()
            self.last_unlock_time = time.time()

        except Exception as e:
            print(f"[경고] 시스템 컨트롤러 잠금 해제 실패: {e}")

    def _tk_on_press(self, event):
        keysym = event.keysym.lower() if event.keysym else ""
        char = event.char.lower() if event.char else ""
        
        if keysym:
            self.pressed_keys.add(keysym)
        if char:
            self.pressed_keys.add(char)

        # OS 조합키(Control, Shift) 대응
        has_ctrl = any(k in self.pressed_keys for k in ['control_l', 'control_r', 'control', 'ctrl'])
        has_shift = any(k in self.pressed_keys for k in ['shift_l', 'shift_r', 'shift'])
        has_m = 'm' in self.pressed_keys

        # 컨트롤러 잠금(is_locked) 상태이거나 외부 이펙트 캔버스(effect_canvas)가 활성화된 상태라면 비밀 단축키 격발
        if has_ctrl and has_shift and has_m:
            is_canvas_active = hasattr(self, 'effect_canvas') and self.effect_canvas is not None
            if self.controller.is_locked or is_canvas_active:
                print("[시스템] 비밀 단축키(Ctrl+Shift+M) 입력 감지! 잠금을 해제합니다.")
                self._trigger_system_unlock()

    def _tk_on_release(self, event):
        keysym = event.keysym.lower() if event.keysym else ""
        char = event.char.lower() if event.char else ""
        
        if keysym in self.pressed_keys:
            self.pressed_keys.remove(keysym)
        if char in self.pressed_keys:
            self.pressed_keys.remove(char)

    def on_closing(self):
        """앱 종료 시 백그라운드 스레드까지 모조리 죽이고 터미널을 즉시 반환하는 강제 종료"""
        print("[시스템] 프로그램을 완전히 종료합니다...")
        
        try:
            if hasattr(self, 'pynput_listener') and self.pynput_listener:
                self.pynput_listener.stop()
            # 1. Tkinter 창 종료
            self.root.quit()
            self.root.destroy()
        except Exception as e:
            pass
        finally:
            # 2. 터미널을 물고 있는 파이썬 프로세스를 강제로 즉각 처형!
            import os
            os._exit(0)