import cv2
import numpy as np
import time
import math
import os
from PIL import Image, ImageTk, ImageDraw, ImageFont

def play_intrusion_sequence(app):
    w, h = app.screen_w, app.screen_h

    # 1. 에셋 및 얼음 마스크 준비(파일을 불러오는데 0.3~0.5초 시간 소요)
    asset_path = "Assets/intrusion_frost_overlay.png"
    if not os.path.exists(asset_path):
        asset_path = os.path.join(os.path.dirname(__file__), 'assets', 'frost.png')

    if os.path.exists(asset_path):
        frost_img = cv2.imread(asset_path, cv2.IMREAD_UNCHANGED)
        frost_img = cv2.resize(frost_img, (w, h))
    else:
        print(f"[경고] 성에 이미지를 찾을 수 없습니다: {asset_path}")
        frost_img = None 

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(mask, (w//2, h//2), (w//3, h//3), 0, 0, 360, 255, -1)
    mask = cv2.GaussianBlur(mask, (101, 101), 0) / 255.0

    fake_bg_path = "Assets/fake_desktop_wallpaper.png"
    if os.path.exists(fake_bg_path):
        fake_desktop_frame = cv2.imread(fake_bg_path)
        fake_desktop_frame = cv2.resize(fake_desktop_frame, (w, h))
    else:
        fake_desktop_frame = np.full((h, w, 3), (30, 30, 30), dtype=np.uint8)

    if hasattr(app, 'captured_desktop') and app.captured_desktop is not None:
        user_workspace_frame = cv2.resize(app.captured_desktop, (w, h))
    else:
        user_workspace_frame = np.zeros((h, w, 3), dtype=np.uint8)
        
    frozen_frame = np.zeros((h, w, 3), dtype=np.uint8)

    # [핵심] 파일 로딩이 모두 끝난 '바로 여기'서부터 타이머를 시작해야 0초부터 애니메이션이 재생됨
    duration = 5.0
    start_time = time.time()
    

    # 2. 5초 연출 루프
    while True:
        # [핵심 방어 1] 이펙트 도중에 단축키로 잠금이 해제되면 즉시 루프 탈출! (화면 작아짐 버그 해결)
        if not app.controller.is_locked:
            print("[시스템] 애니메이션 강제 중단 (잠금 해제됨)")
            return 

        elapsed = time.time() - start_time
        if elapsed > duration:
            break

        # Phase 1: 0 ~ 1.5초 (화면 얼어붙기 & 주문 텍스트 완성)
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
            
            # 글씨 출력 
            final_frame = _draw_text(frame, elapsed, w, h)
            frozen_frame = final_frame.copy()

        # Phase 2: 1.5초 ~ 5초 (글씨가 다 나온 상태에서 천천히 화면 전환)
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

            # Phase 2: 1.5초 ~ 5초 내부
            blended_bg = (fake_desktop_frame * wipe_mask_3d + frozen_frame * (1.0 - wipe_mask_3d)).astype(np.uint8)
            
            # ⭐️ 이름 변경
            final_frame = _render_expanding_portal(blended_bg, wipe_progress, w, h, current_radius)

        cv2_im_rgb = cv2.cvtColor(final_frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(cv2_im_rgb)
        app.photo = ImageTk.PhotoImage(image=pil_img)
        app.canvas.create_image(0, 0, image=app.photo, anchor="nw")
        
        app.root.update()

    # 연출 종료 후 가짜 화면 고정할 때도, 잠겨있는 상태인지 확인
    if app.controller.is_locked:
        cv2_im_rgb = cv2.cvtColor(fake_desktop_frame, cv2.COLOR_BGR2RGB)
        app.photo = ImageTk.PhotoImage(image=Image.fromarray(cv2_im_rgb))
        app.canvas.create_image(0, 0, image=app.photo, anchor="nw")
        app.root.focus_force()
        app.root.update()


# --- 헬퍼 함수들 ---

def _render_expanding_portal(base_frame, progress, w, h, current_radius):
    """'선 긋기'를 완전히 배제하고 Numpy 그라데이션 수학 연산으로 만든 완벽히 부드러운 마법 빛무리"""
    # 진행도에 따라 서서히 사라지는 투명도
    alpha = max(0.0, 1.0 - (progress * 1.5))
    if alpha <= 0 or current_radius < 1:
        return base_frame

    # 1. 화면 전체 픽셀에서 중심까지의 거리를 계산 (선 함수 없이 픽셀 단위 계산)
    Y, X = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((X - w/2)**2 + (Y - h/2)**2)

    # 2. 경계선(current_radius)을 기준으로 양옆으로 퍼지는 부드러운 링 마스크 계산
    glow_thickness = 130.0 # 숫자가 커질수록 빛이 솜사탕처럼 더 넓고 부드럽게 퍼집니다.
    dist_to_edge = np.abs(dist_from_center - current_radius)
    
    # 3. 거리가 경계선에 가까울수록 1.0, 멀어질수록 0.0이 되는 마스크
    glow_mask = np.clip(1.0 - (dist_to_edge / glow_thickness), 0.0, 1.0)
    
    # 단순히 선형으로 줄어들지 않고, 빛처럼 자연스럽게 흩어지도록 곡선(제곱) 처리
    glow_mask = (glow_mask ** 2) * alpha
    glow_mask_3d = glow_mask[:, :, np.newaxis]

    # 4. 몽환적인 얼음빛(Ice Blue & White) 컬러 레이어 생성 (BGR 배열)
    glow_layer = np.full(base_frame.shape, (255, 240, 200), dtype=np.float32)

    # 5. 빛무리 레이어에 마스크를 곱해서 '더하기(Additive)' 모드로 얹기 
    # (선을 그린 것이 아니므로 어색한 테두리나 경계선이 절대 생기지 않습니다!)
    glow_overlay = (glow_layer * glow_mask_3d).astype(np.uint8)
    
    return cv2.add(base_frame, glow_overlay)


def _draw_text(frame, elapsed, w, h):
    """완벽하게 정중앙에 고정된 리얼한 타이핑 이펙트 (짤림 버그 수정)"""
    # 1. 폰트 짤림 방지를 위해 맨 뒤에 공백 한 칸 추가 ("m"이 숨쉴 공간 확보)
    text = "Repello Muggletum " 
    
    # 2. 소수점 오차를 무시하고 1.5초가 지나면 무조건 전체 글자가 다 뜨도록 강제!
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
    # 3. Mac 화면에서 글자가 너무 길어져서 양옆이 잘리는 현상 방지 (0.15 -> 0.12로 축소)
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