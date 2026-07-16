import sys
import time
import threading
import tkinter as tk
from ui.app_window import AppWindow
from ai_detector.ai_detector import MuggleBlockerDetector

def ai_detection_thread(app, detector):
    """실시간 웹캠 프레임을 분석하여 잠금 상태를 통제하는 백그라운드 AI 스레드"""
    print("[AI] 실시간 감지 스레드가 구동되었습니다.")
    
    while True:
        # GUI 시스템이 정지 상태일 때는 감지를 보류하고 대기
        if not app.is_running:
            time.sleep(0.5)
            continue
            
        # 비디오 스트리머로부터 최신 원본 프레임을 획득
        frame = app.streamer.get_raw_frame() if hasattr(app.streamer, 'get_raw_frame') else None
        
        if frame is not None:
            # AI 분석 모듈에 프레임 전달
            detection_result = detector.process_frame(frame)
            
            # 1. 인트루더(머글 침입) 혹은 사용자 부재(AWAY) 감지 시
            if detection_result in ["INTRUSION", "AWAY"]:
                # Lock Screen 호출 (입력 차단 및 UI 잠금)
                if not app.controller.is_locked:
                    app.root.after(0, lambda r=detection_result: app.controller.lock_screen(r))
            
            # 2. 본인 정상 감지 시 (잠금 해제는 단축키 Ctrl+Shift+M 전용이 아닐 경우 자동 해제 옵션)
            # elif detection_result == "NORMAL" and app.controller.is_locked:
            #     app.root.after(0, app.controller.unlock_screen)
                
        time.sleep(0.03) # 30 FPS 주기 조율

def main():
    # 1. 메인 GUI 인스턴스 가동
    root = tk.Tk()
    app = AppWindow(root)
    
    # 2. AI 탐지기 클래스 가동
    try:
        detector = MuggleBlockerDetector()
    except Exception as e:
        print(f"[오류] AI 감지 모듈 초기화 실패: {e}")
        detector = None

    # 3. AI 탐지 루프를 독립 스레드로 분리하여 GUI 프리징(Freeze) 예방
    if detector is not None:
        ai_thread = threading.Thread(target=ai_detection_thread, args=(app, detector), daemon=True)
        ai_thread.start()

    # 4. Tkinter 메인 루프 실행
    root.mainloop()

if __name__ == "__main__":
    main()