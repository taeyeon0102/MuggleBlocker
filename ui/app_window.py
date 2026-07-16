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
        self.root.geometry("700x550")
        
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
        
        # Canvas 내부 이미지 갱신용 객체 ID 저장 변수
        self.canvas_image_id = None
        self.photo = None # 이미지 객체가 가비지 컬렉터에 의해 사라지는 것을 방지

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
            
            # 비디오 감지 루프 시작
            self.update_frame()
        else:
            self.is_running = False
            self.status_label.config(text="시스템 정지됨", fg="red")
            self.btn_toggle.config(text="방어막 켜기 (ON)")
            
            # 타이머 루프 예약 취소
            if self.loop_id is not None:
                self.root.after_cancel(self.loop_id)
                self.loop_id = None
                
            self.canvas.delete("all")
            self.canvas_image_id = None
            self.user_registered = False # 본인 등록 플래그 리셋
            
    def update_frame(self):
        """메인 비디오 프레임 갱신 및 AI 분석 피드백 루프"""
        if not self.is_running:
            return
            
        # AI 디텍터 상태 피드백 확인 (None 체크 및 안전장치)
        current_status = "NORMAL"
        if self.detector is not None:
            current_status = self.detector.get_status()

        # [추가] 사용자가 다시 정상 감지(NORMAL)되면 자동으로 보안 잠금을 해제합니다.
        if current_status == "NORMAL" and self.controller.is_locked:
            print("[시스템] 사용자 본인 확인 완료 -> 보안 잠금 해제!")
            self._trigger_system_unlock()

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
            
            # 잠금 상태에서도 해제를 계속 감시하기 위해 실시간 연산은 백그라운드 구동
            ret, frame_rgb = self.streamer.get_frame(intrusion_mode=False)
            if ret and frame_rgb is not None:
                self._analyze_frame(frame_rgb)

        else:
            # [상태 2] 정상 감시 상태인 경우: AI 분석 피드백 적용
            intrusion_active = False
            if current_status == "NORMAL":
                self.status_label.config(text="보안 감시 중 (정상 상태)", fg="green")
            elif current_status == "AWAY":
                self.status_label.config(text="사용자 자리 비움 (AWAY)", fg="orange")
                # [수정] 자리를 비웠을 때도 화면을 차단하기 위해 잠금 컨트롤러를 격발합니다.
                self._trigger_system_lock()
            elif current_status == "INTRUSION":
                self.status_label.config(text="🚨 머글 침입 감지! (INTRUSION) 🚨", fg="red")
                intrusion_active = True
                
                # 머글 침입 시 잠금 컨트롤러 가동
                self._trigger_system_lock()

            # 실시간 프레임 취득 (침입 중일 때 성에 오버레이가 자연스럽게 합성됨)
            ret, frame_rgb = self.streamer.get_frame(intrusion_mode=intrusion_active)
            
            if ret and frame_rgb is not None:
                # 본인 등록 안 된 경우 최초 1회 자동 등록
                if not self.user_registered and self.detector is not None:
                    if self.detector.register_user_face(frame_rgb):
                        self.user_registered = True
                        print("[시스템] 사용자 얼굴 등록 완료!")

                # AI 모듈 백그라운드 분석 전달
                self._analyze_frame(frame_rgb)
                
                # RGB 이미지를 Tkinter용 이미지 객체로 메모리 최적화 변환
                img = Image.fromarray(frame_rgb)
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
            if hasattr(self.controller, "lock") and callable(getattr(self.controller, "lock")):
                self.controller.lock()
            elif hasattr(self.controller, "lock_system") and callable(getattr(self.controller, "lock_system")):
                self.controller.lock_system()
            else:
                self.controller.is_locked = True
        except Exception as e:
            print(f"[경고] 시스템 컨트롤러 잠금 전환 실패: {e}")

    def _trigger_system_unlock(self):
        """잠금을 실행한 것과 대칭되게 안전하게 잠금을 해제(Unlock)하는 안전 트리거 함수"""
        try:
            if hasattr(self.controller, "unlock") and callable(getattr(self.controller, "unlock")):
                self.controller.unlock()
            elif hasattr(self.controller, "unlock_system") and callable(getattr(self.controller, "unlock_system")):
                self.controller.unlock_system()
            else:
                self.controller.is_locked = False
        except Exception as e:
            print(f"[경고] 시스템 컨트롤러 잠금 해제 실패: {e}")