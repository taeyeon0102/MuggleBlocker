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
        except:
            pass
    
    # 2. 메인 UI 레이아웃을 건드리지 않고 전체 화면을 덮어버릴 이펙트 전용 Canvas 생성
    app_instance.effect_canvas = tk.Canvas(
        app_instance.root, 
        width=app_instance.screen_w, 
        height=app_instance.screen_h, 
        bg="black", 
        highlightthickness=0
    )
    # 기존 컴포넌트 위에 유연하게 올리기 위해 place 사용
    app_instance.effect_canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
    
    print("[이펙트] 💤 사용자의 부재(AWAY) 감지: 풀스크린 위장 화면을 연출합니다.")
    
    # 기획안 명세 기준: 모니터 전체 해상도로 맞춤 리사이즈된 위장 바탕화면 렌더링
    if hasattr(app_instance, 'fake_photo_full') and app_instance.fake_photo_full:
        app_instance.effect_canvas.create_image(0, 0, anchor=tk.NW, image=app_instance.fake_photo_full)
    else:
        # 에셋을 로드하지 못했을 때를 대비한 미니멀 보안 폴백 텍스트
        app_instance.effect_canvas.create_text(
            app_instance.screen_w // 2, app_instance.screen_h // 2,
            text="🔒 System Locked (Mischief Managed)",
            fill="#444444", font=("Helvetica", 24, "bold")
        )
        
    # 완벽한 위장을 위해 스크린 정중앙 하단에 시선에 띄지 않는 은은한 보호 문구 추가
    app_instance.effect_canvas.create_text(
        app_instance.screen_w // 2, app_instance.screen_h - 60,
        text="Muggle Blocker 가 백그라운드에서 보안 감시 중입니다.",
        fill="#333333", font=("Helvetica", 12, "italic")
    )