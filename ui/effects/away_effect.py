import tkinter as tk

def play_away_sequence(app_instance):
    """
    현재 앱의 상태가 AWAY(부재)일 때 작동하는 
    풀스크린 바탕화면 위장 및 보안 이펙트 시퀀스입니다.
    """
    # 1. 이미 열려 있는 이전 이펙트 레이어가 있다면 화면에서 안전하게 제거
    if hasattr(app_instance, 'effect_canvas') and app_instance.effect_canvas:
        try:
            app_instance.effect_canvas.place_forget()
            app_instance.effect_canvas.destroy()
        except Exception:
            pass
    
    # 2. 메인 UI 레이아웃을 건드리지 않고 전체 화면을 덮어버릴 이펙트 전용 Canvas 생성
    app_instance.effect_canvas = tk.Canvas(
        app_instance.root, 
        width=app_instance.screen_w, 
        height=app_instance.screen_h, 
        bg="black", 
        highlightthickness=0
    )
    app_instance.effect_canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
    
    # ⭐️ 캔버스에 직접 키 이벤트를 통째로 바인딩하고 강제 포커스 획득
    app_instance.effect_canvas.bind_all("<KeyPress>", app_instance._tk_on_press)
    app_instance.effect_canvas.bind_all("<KeyRelease>", app_instance._tk_on_release)
    app_instance.effect_canvas.focus_force()
    
    print("[이펙트] 💤 주인의 부재(AWAY) 감지: 풀스크린 위장 화면을 연출합니다.")
    
    # 3. 위장 바탕화면 이미지 및 안내 문구 렌더링
    if hasattr(app_instance, 'fake_photo_full') and app_instance.fake_photo_full:
        app_instance.effect_canvas.create_image(0, 0, anchor=tk.NW, image=app_instance.fake_photo_full)
    else:
        app_instance.effect_canvas.create_text(
            app_instance.screen_w // 2, app_instance.screen_h // 2,
            text="🔒 System Locked (Mischief Managed)",
            fill="#444444", font=("Helvetica", 24, "bold")
        )
        
    app_instance.effect_canvas.create_text(
        app_instance.screen_w // 2, app_instance.screen_h - 60,
        text="Muggle Blocker 가 백그라운드에서 보안 감시 중입니다.",
        fill="#333333", font=("Helvetica", 12, "italic")
    )