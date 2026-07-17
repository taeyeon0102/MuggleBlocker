from pynput import keyboard

class SystemController:
    def __init__(self):
        self.is_locked = False # 차단 제어 플래그

    def lock_screen(self):
        if self.is_locked:
            return 
        self.is_locked = True
        print(f"화면 블럭")
        # pynput 리스너 없이 UI 오버레이와 연동

    def unlock_screen(self):
        if not self.is_locked:
            return
        self.is_locked = False
        print("화면 블럭 해제")

    """
    def __init__(self):
        # 1. 상태 변수
        self.is_locked = False

        # 2. 방어막 (입력 차단) 리스너 함수 
        self.keyboard_block_listener = None
        # self.mouse_block_listener = None

        # 3. 현재 눌린 키 저장
        self.current_keys = set()

    # AI 파이프라인에서 사람 감지/자리 비움 시 호출하는 함수
    def lock_screen(self):

        # 1. 이미 잠겨있으면(활성화되어 있으면) 무시
        if self.is_locked:
            return 
        
        # 2. 화면 잠그는 변수 활성화
        self.is_locked = True
        self.current_keys.clear()

        # 3. 풀스크린 띄우는 코드
        print("화면 블럭")

        # 4. 키보드 입력을 차단하는 리스너 실행
        self.keyboard_block_listener = keyboard.Listener(
            on_press = self._on_press,
            on_release = self._on_release,
            suppress = False # 맥 환경에서 충돌로 자꾸 프로그램이 터지므로,,, ㅠㅜ
            )
        self.keyboard_block_listener.start()
        

        # 5. 마우스 입력을 차단하는 리스너 실행
        # self.mouse_block_listener = mouse.Listener(suppress = True)
        # self.mouse_block_listener.start()

    # 비밀 단축키가 눌렸을 때 자체적으로 호출하는 함수
    def unlock_screen(self):
        # 1. 잠겨있지 않으면 무시
        if not self.is_locked:
            return
        
        # 2. 화면 잠그는 변수 끄기
        self.is_locked = False
        
        # 3. 풀스크린 창 숨기기 (원래 화면 복귀)
        print("화면 블럭 해제")

        # 4. 키보드 차단 리스너 중지
        if self.keyboard_block_listener is not None:
            self.keyboard_block_listener.stop()
            self.keyboard_block_listener = None
        

        # 5. 마우스 차단 리스너 중지
        # if self.mouse_block_listener is not None:
        #     self.mouse_block_listener.stop()
        #     self.mouse_block_listener = None

    # 키가 눌렸을 때 실행되는 함수 (내부용)
    def _on_press(self, key):
        # 눌린 키 기록
        self.current_keys.add(key)

        # 1. ctrl 키 확인
        is_ctrl = any(k in self.current_keys for k in [keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r ])

        # 2. shift 키 확인
        is_shift = any(k in self.current_keys for k in [keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r])

        # 3. m 키 확인
        is_m = False
        for k in self.current_keys:
            if hasattr(k, 'char') and k.char and k.char.lower() == 'm':
                is_m = True
                break

        # 세 키가 동시에 눌리는지 확인
        if is_ctrl and is_shift and is_m:
            self.unlock_screen()

    # 키에서 손을 뗐을 때 실행되는 함수 (내부용)
    def _on_release(self, key):
        # 손을 뗀 키 제거
        if key in self.current_keys:
            self.current_keys.remove(key)

        # 문자 키 제거 
        if hasattr(key, 'char') and key.char:
            self.current_keys = {k for k in self.current_keys if not (hasattr(k, 'char') and k.char == key.char)}


if __name__ == "__main__":
    import time
    
    controller = SystemController()
    print("시스템 컨트롤러 가동. (테스트를 위해 3초 뒤 화면이 잠깁니다)")
    time.sleep(3)
    
    # 파이프라인이 머글을 감지했다고 가정하고 잠금 함수 강제 호출
    controller.lock_screen("INTRUSION")
    
    # 메인 스레드가 꺼지지 않도록 대기
    # 화면이 잠기면 키보드가 안 먹히지만, Ctrl+Shift+M을 누르면 풀립니다!
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
        
"""