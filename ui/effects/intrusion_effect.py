import cv2
import numpy as np
import time
import math
import os
from PIL import Image, ImageTk, ImageDraw, ImageFont

def play_intrusion_sequence(app):
    w, h = app.screen_w, app.screen_h

    # =========================================================
    # 0. [1번 아이디어] 침입자 캡처 이미지 로그 자동 저장 및 준비
    # =========================================================
    os.makedirs("logs", exist_ok=True)
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    intruder_log_path = f"logs/intruder_{timestamp_str}.png"

    # 웹캠에서 현재 찍히고 있는 침입자 프레임 가져오기
    ret, current_frame = app.streamer.get_frame(intrusion_mode=True)
    if not ret or current_frame is None:
        # 실패 시 검은 화면 예외 처리
        intruder_bgr = np.zeros((h, w, 3), dtype=np.uint8)
    else:
        # RGB -> BGR 변환
        intruder_bgr = cv2.cvtColor(current_frame, cv2.COLOR_RGB2BGR)

    # 1. 침입자 원본 이미지 파일로 로그 저장
    try:
        cv2.imwrite(intruder_log_path, intruder_bgr)
        print(f"[시스템] 🚨 침입자 얼굴 캡처 완료! 저장 경로: {intruder_log_path}")
    except Exception as e:
        print(f"[경고] 침입자 로그 저장 실패: {e}")

    # 2. 캡처본을 아즈카반 현수배서용 흑백(Grayscale) 목판화 느낌으로 가공
    intruder_gray = cv2.cvtColor(intruder_bgr, cv2.COLOR_BGR2GRAY)
    # 명암 대비 극대화 (빈티지 질감 연출)
    intruder_gray = cv2.equalizeHist(intruder_gray)
    intruder_processed = cv2.cvtColor(intruder_gray, cv2.COLOR_GRAY2BGR)

    # =========================================================
    # 1. 에셋 준비 (양피지 배경, 성에, 배경화면 등)
    # =========================================================
    bg_path = "Assets/away_parchment_bg.jpg"
    if os.path.exists(bg_path):
        parchment_bg = cv2.imread(bg_path)
        parchment_bg = cv2.resize(parchment_bg, (w, h))
    else:
        # 양피지 이미지가 없을 경우 누런 빈티지 톤 대처
        parchment_bg = np.full((h, w, 3), (200, 225, 240), dtype=np.uint8)

    # 아즈카반 수배서 포스터 레이아웃 완성 (양피지 위에 흑백 수배 사진 및 문구 합성)
    azkaban_poster = _render_azkaban_poster(parchment_bg, intruder_processed, w, h)

    asset_path = "Assets/intrusion_frost_overlay.png"
    if not os.path.exists(asset_path):
        asset_path = os.path.join(os.path.dirname(__file__), 'assets', 'frost.png')

    if os.path.exists(asset_path):
        frost_img = cv2.imread(asset_path, cv2.IMREAD_UNCHANGED)
        frost_img = cv2.resize(frost_img, (w, h))
    else:
        frost_img = None 

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(mask, (w//2, h//2), (w//3, h//3), 0, 0, 360, 255, -1)
    mask = cv2.GaussianBlur(mask, (101, 101), 0) / 255.0

    if hasattr(app, 'captured_desktop') and app.captured_desktop is not None:
        user_workspace_frame = cv2.resize(app.captured_desktop, (w, h))
    else:
        user_workspace_frame = np.zeros((h, w, 3), dtype=np.uint8)
        
    frozen_frame = np.zeros((h, w, 3), dtype=np.uint8)

    duration = 5.0
    start_time = time.time()
    
    # =========================================================
    # 2. 5초 애니메이션 시퀀스 루프
    # =========================================================
    while True:
        if not app.controller.is_locked:
            print("[시스템] 애니메이션 강제 중단 (단축키로 잠금 해제됨)")
            return 

        elapsed = time.time() - start_time
        if elapsed > duration:
            break

        # Phase 1: 0 ~ 1.5초 (화면 얼어붙기 & Repello Muggletum 주문 출력)
        if elapsed <= 1.5:
            frame = user_workspace_frame.copy()
            fade = min(elapsed / 1.5, 1.0) 

            if frost_img is not None:
                mask_3d = mask[:, :, np.newaxis]
                if frost_img.shape[2] == 4:
                    f_rgb = frost_img[:, :, :3]
                    f_alpha = (frost_img[:, :, 3] / 255.0) * fade
                    f_alpha_3d = f_alpha[:, :, np.newaxis]
                    final_alpha = f_alpha_3d * (1.0 - mask_3d)
                    
                    blended = f_rgb * final_alpha + frame.astype(np.float32) * (1.0 - final_alpha)
                    frame = np.clip(blended, 0, 255).astype(np.uint8)
                else:
                    f_rgb = frost_img * fade
                    f_rgb = f_rgb * (1.0 - mask_3d) 
                    frame = cv2.add(frame, f_rgb.astype(np.uint8))
            
            # 얼음 주문 텍스트 렌더링
            final_frame = _draw_text(frame, elapsed, w, h)
            frozen_frame = final_frame.copy()

        # Phase 2: 1.5초 ~ 5초 (얼음 화면이 열리며 아즈카반 수배서 포스터로 전환)
        else:
            wipe_progress = (elapsed - 1.5) / 3.5
            ease_progress = wipe_progress ** 1.2 
            
            max_radius = math.hypot(w/2, h/2)
            current_radius = max_radius * ease_progress

            Y, X = np.ogrid[:h, :w]
            dist_from_center = np.sqrt((X - w/2)**2 + (Y - h/2)**2)
            
            edge_softness = 150 
            wipe_mask = np.clip((current_radius - dist_from_center) / edge_softness + 0.5, 0, 1)
            wipe_mask_3d = wipe_mask[:, :, np.newaxis]

            # 얼음 화면 -> 아즈카반 수배서 포스터(azkaban_poster)로 트랜지션
            blended_bg = (azkaban_poster * wipe_mask_3d + frozen_frame * (1.0 - wipe_mask_3d)).astype(np.uint8)
            
            final_frame = _render_expanding_portal(blended_bg, wipe_progress, w, h, current_radius)

        # 화면 갱신
        cv2_im_rgb = cv2.cvtColor(final_frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(cv2_im_rgb)
        app.photo = ImageTk.PhotoImage(image=pil_img)
        app.canvas.create_image(0, 0, image=app.photo, anchor="nw")
        
        app.root.update()

    # 연출 종료 후 아즈카반 수배서 화면 박제 고정
    if app.controller.is_locked:
        cv2_im_rgb = cv2.cvtColor(azkaban_poster, cv2.COLOR_BGR2RGB)
        app.photo = ImageTk.PhotoImage(image=Image.fromarray(cv2_im_rgb))
        app.canvas.create_image(0, 0, image=app.photo, anchor="nw")
        app.root.focus_force()
        app.root.update()


# --- 헬퍼 함수들 ---

def _render_azkaban_poster(bg_frame, intruder_bgr, w, h):
    """양피지 바탕(bg_frame) 위에 아즈카반 수배서 타이포그래피와 흑백 침입자 사진을 박제하는 렌더러"""
    pil_img = Image.fromarray(cv2.cvtColor(bg_frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    # 1. 폰트 세팅 (시스템 세리프 폰트 fallback)
    serif_font_path = "Georgia.ttf" # Windows / macOS 공통 표준 세리프
    try:
        title_font = ImageFont.truetype(serif_font_path, int(h * 0.08))
        subtitle_font = ImageFont.truetype(serif_font_path, int(h * 0.05))
        caution_font = ImageFont.truetype(serif_font_path, int(h * 0.035))
    except IOError:
        # 폰트 로드 실패 시 디폴트
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        caution_font = ImageFont.load_default()

    # 색상 정의 (아즈카반 특유의 다크 브라운 / 잉크 블랙)
    ink_color = (25, 20, 15)

    # 2. 상단 헤더 문구 ("MUGGLE DETECTED")
    title_text = "MUGGLE DETECTED"
    tb = draw.textbbox((0, 0), title_text, font=title_font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text(((w - tw) // 2, int(h * 0.08)), title_text, font=title_font, fill=ink_color)

    sub_text = "AZKABAN WARNING - INTRUDER #001"
    stb = draw.textbbox((0, 0), sub_text, font=subtitle_font)
    stw, sth = stb[2] - stb[0], stb[3] - stb[1]
    draw.text(((w - stw) // 2, int(h * 0.17)), sub_text, font=subtitle_font, fill=ink_color)

    # 3. 중앙 침입자 흑백 사진 액자 박제 영역 계산
    box_w = int(w * 0.38)
    box_h = int(h * 0.45)
    box_x = (w - box_w) // 2
    box_y = int(h * 0.26)

    # 테두리 액자 선 그리기
    draw.rectangle([box_x - 6, box_y - 6, box_x + box_w + 6, box_y + box_h + 6], outline=ink_color, width=4)

    # 침입자 이미지를 액자 크기에 맞게 리사이즈 후 PIL에 안착
    intruder_rgb = cv2.cvtColor(intruder_bgr, cv2.COLOR_BGR2RGB)
    intruder_pil = Image.fromarray(intruder_rgb).resize((box_w, box_h))
    pil_img.paste(intruder_pil, (box_x, box_y))

    # 4. 하단 경고 문구 ("WANTED", "APPROACH WITH EXTREME CAUTION")
    wanted_text = "WANTED"
    wtb = draw.textbbox((0, 0), wanted_text, font=title_font)
    wtw = wtb[2] - wtb[0]
    draw.text(((w - wtw) // 2, int(h * 0.74)), wanted_text, font=title_font, fill=ink_color)

    caution_text = "APPROACH WITH EXTREME CAUTION"
    ctb = draw.textbbox((0, 0), caution_text, font=caution_font)
    ctw = ctb[2] - ctb[0]
    draw.text(((w - ctw) // 2, int(h * 0.84)), caution_text, font=caution_font, fill=ink_color)

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def _render_expanding_portal(base_frame, progress, w, h, current_radius):
    """Numpy 그라데이션 수학 연산으로 만든 완벽히 부드러운 마법 빛무리"""
    alpha = max(0.0, 1.0 - (progress * 1.5))
    if alpha <= 0 or current_radius < 1:
        return base_frame

    Y, X = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((X - w/2)**2 + (Y - h/2)**2)

    glow_thickness = 130.0
    dist_to_edge = np.abs(dist_from_center - current_radius)
    
    glow_mask = np.clip(1.0 - (dist_to_edge / glow_thickness), 0.0, 1.0)
    glow_mask = (glow_mask ** 2) * alpha
    glow_mask_3d = glow_mask[:, :, np.newaxis]

    glow_layer = np.full(base_frame.shape, (255, 240, 200), dtype=np.float32)
    glow_overlay = (glow_layer * glow_mask_3d).astype(np.uint8)
    
    return cv2.add(base_frame, glow_overlay)


def _draw_text(frame, elapsed, w, h):
    """정중앙 고정 타이핑 이펙트"""
    text = "Repello Muggletum " 
    
    if elapsed >= 1.5:
        visible_text = text
    else:
        char_count = int((elapsed / 1.5) * len(text))
        visible_text = text[:char_count]
    
    if len(visible_text) == 0:
        return frame
        
    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    
    font_path = "Assets/font_harry_p.ttf"
    font_size = int(h * 0.12) 
    try:
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        font = ImageFont.load_default()

    full_bbox = draw.textbbox((0, 0), text, font=font)
    full_text_w = full_bbox[2] - full_bbox[0]
    full_text_h = full_bbox[3] - full_bbox[1]
    
    tx = (w - full_text_w) // 2
    ty = (h - full_text_h) // 2

    font_color = (200, 240, 255) 
    stroke_color = (0, 30, 60) 

    draw.text((tx, ty), visible_text, font=font, fill=font_color, 
              stroke_width=6, stroke_fill=stroke_color)
    
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)