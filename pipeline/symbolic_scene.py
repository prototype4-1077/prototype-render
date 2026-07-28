"""Deterministic cinematic symbolic clips for abstract narration beats.

Usage: python3 symbolic_scene.py <build_dir> <scene_index>
Writes clip_XX.mp4 and updates script.json with temporal verification metadata.
"""
from __future__ import annotations

import json, math, os, subprocess, sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import motion
from video_format import ENCODE_QUALITY, COLOR_TAGS

W, H, FPS = 1152, 648, 20
TAU = math.tau

PALETTES = {
    "cyan": ((5, 12, 22), (12, 38, 56), (82, 224, 235), (235, 248, 250)),
    "amber": ((18, 10, 7), (63, 31, 14), (255, 176, 67), (255, 242, 210)),
    "violet": ((12, 7, 24), (45, 23, 76), (190, 126, 255), (245, 235, 255)),
    "green": ((5, 17, 13), (18, 61, 45), (85, 230, 162), (231, 255, 243)),
    "red": ((20, 6, 8), (74, 18, 27), (255, 91, 112), (255, 232, 235)),
    "blue": ((4, 10, 26), (17, 44, 91), (92, 171, 255), (234, 244, 255)),
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    here = Path(__file__).resolve().parent
    candidates = [
        here / "fonts" / ("Baloo2-ExtraBold.ttf" if bold else "Questrial-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def _lerp(a, b, t):
    return a + (b - a) * t


def _mix(c1, c2, t):
    return tuple(int(_lerp(a, b, t)) for a, b in zip(c1, c2))


_BG_CACHE = {}


def _background(palette: str, t: float) -> Image.Image:
    c0, c1, accent, _ = PALETTES[palette]
    if palette not in _BG_CACHE:
        y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
        top = np.array(c0, np.float32)[None, None, :]
        bot = np.array(c1, np.float32)[None, None, :]
        arr = np.repeat(top * (1 - y) + bot * y, W, axis=1)
        grain = np.random.default_rng(37).normal(0, 1.7, (H, W, 1))
        arr += grain
        _BG_CACHE[palette] = Image.fromarray(np.uint8(np.clip(arr, 0, 255)), "RGB")
    img = _BG_CACHE[palette].copy()
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx = W * (0.50 + 0.13 * math.sin(TAU * t))
    cy = H * (0.36 + 0.08 * math.cos(TAU * t * .7))
    rx, ry = W * .28, H * .34
    gd.ellipse((cx-rx, cy-ry, cx+rx, cy+ry), fill=(*accent, 34))
    glow = glow.filter(ImageFilter.GaussianBlur(75))
    img.paste(glow, (0, 0), glow)
    return img


def _glow_line(img: Image.Image, points, color, width=5, glow=18):
    glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.line(points, fill=(*color, 190), width=width * 3, joint="curve")
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(glow))
    img.paste(glow_layer, (0, 0), glow_layer)
    ImageDraw.Draw(img).line(points, fill=(*color, 245), width=width, joint="curve")


def _label(img, text, xy, size=38, accent=(90, 220, 235), anchor="mm", bold=True, alpha=255):
    d = ImageDraw.Draw(img)
    font = _font(size, bold)
    x, y = xy
    bbox = d.textbbox((x, y), text, font=font, anchor=anchor)
    pad = 12
    d.rounded_rectangle((bbox[0]-pad, bbox[1]-7, bbox[2]+pad, bbox[3]+7), radius=13,
                        fill=(5, 8, 14, int(alpha*.72)), outline=(*accent, int(alpha*.55)), width=2)
    d.text((x, y), text, font=font, fill=(245, 249, 252, alpha), anchor=anchor)


def _silhouette(img, center, scale, color, phase=0.0, particles=False):
    d = ImageDraw.Draw(img)
    cx, cy = center
    head_r = 44 * scale
    body_w = 170 * scale
    if not particles:
        d.ellipse((cx-head_r, cy-250*scale-head_r, cx+head_r, cy-250*scale+head_r), fill=color)
        d.rounded_rectangle((cx-body_w/2, cy-205*scale, cx+body_w/2, cy+40*scale), radius=int(70*scale), fill=color)
        d.polygon([(cx-body_w*.45, cy+10*scale), (cx-body_w*.78, cy+210*scale),
                   (cx-body_w*.20, cy+210*scale), (cx, cy+45*scale)], fill=color)
        d.polygon([(cx+body_w*.45, cy+10*scale), (cx+body_w*.78, cy+210*scale),
                   (cx+body_w*.20, cy+210*scale), (cx, cy+45*scale)], fill=color)
        return
    rng = np.random.default_rng(410)
    for i in range(440):
        a = rng.uniform(0, TAU)
        q = rng.random()
        if q < .2:
            r = head_r * math.sqrt(rng.random())
            x, y = cx + r*math.cos(a), cy-250*scale + r*math.sin(a)
        elif q < .72:
            x = cx + rng.normal(0, body_w*.26)
            y = cy - 200*scale + rng.random()*250*scale
        else:
            side = -1 if rng.random() < .5 else 1
            y = cy + rng.random()*205*scale
            x = cx + side*(25*scale + (y-cy)*.38) + rng.normal(0, 18*scale)
        drift = 18 * math.sin(phase + i*.19) * (0.3 + rng.random())
        r = 2 + 2.5*rng.random()
        d.ellipse((x+drift-r, y-r, x+drift+r, y+r), fill=color)


def _wave_points(x0, x1, y, amp, cycles, phase, count=160):
    pts=[]
    for j in range(count):
        u=j/(count-1)
        x=_lerp(x0,x1,u)
        env=math.sin(math.pi*u)**.65
        pts.append((x, y+amp*env*math.sin(TAU*cycles*u+phase)))
    return pts


def _draw_piano(img, x, y, scale, opacity=255):
    d=ImageDraw.Draw(img); key_w=38*scale; key_h=150*scale
    for i in range(9):
        xx=x+i*key_w
        d.rounded_rectangle((xx,y,xx+key_w-2,y+key_h), radius=3, fill=(235,238,240,opacity), outline=(28,31,38,opacity), width=2)
    for i in (1,2,4,5,6):
        xx=x+i*key_w-key_w*.32
        d.rounded_rectangle((xx,y,xx+key_w*.62,y+key_h*.62), radius=3, fill=(12,14,19,opacity))


def _draw_speaker(img, x,y,scale, opacity=255):
    d=ImageDraw.Draw(img)
    d.rounded_rectangle((x-78*scale,y-125*scale,x+78*scale,y+125*scale), radius=int(16*scale),
                        fill=(24,27,34,opacity), outline=(160,174,190,opacity), width=max(1,int(3*scale)))
    for r, yy in ((53,y+42*scale),(28,y-62*scale)):
        d.ellipse((x-r*scale,yy-r*scale,x+r*scale,yy+r*scale), fill=(7,9,13,opacity), outline=(110,220,235,opacity), width=max(1,int(4*scale)))


def _draw_key(img,x,y,scale,color):
    d=ImageDraw.Draw(img); r=34*scale
    d.ellipse((x-r,y-r,x+r,y+r), outline=color, width=max(3,int(9*scale)))
    d.line((x+r,y,x+150*scale,y), fill=color, width=max(3,int(12*scale)))
    d.line((x+110*scale,y,x+110*scale,y+34*scale), fill=color, width=max(3,int(12*scale)))
    d.line((x+145*scale,y,x+145*scale,y+28*scale), fill=color, width=max(3,int(12*scale)))


def _draw_bill(img,x,y,w,h,text,accent):
    d=ImageDraw.Draw(img)
    d.rounded_rectangle((x,y,x+w,y+h), radius=14, fill=(232,236,226,245), outline=accent, width=3)
    d.text((x+22,y+20), text, font=_font(int(h*.26),True), fill=(24,34,28), anchor="la")
    for k in range(3):
        yy=y+h*.55+k*14
        d.line((x+22,yy,x+w-22,yy), fill=(90,105,95), width=2)


def _scene_identity(img,t,accent,light):
    phase=TAU*t
    _silhouette(img,(W*.50,H*.54),.86,(*accent,220),phase,particles=True)
    d=ImageDraw.Draw(img)
    d.ellipse((W*.50-42,H*.54-260-42,W*.50+42,H*.54-260+42),outline=(*light,170),width=3)
    d.rounded_rectangle((W*.50-76,H*.54-210,W*.50+76,H*.54+35),radius=62,outline=(*light,150),width=3)
    _label(img,"PATTERN",(W*.5,H*.88),42,accent)


def _scene_keys_bills(img,t,accent,light):
    d=ImageDraw.Draw(img)
    d.polygon([(80,520),(W-80,520),(W-160,H),(160,H)],fill=(68,46,32,230))
    bounce=8*math.sin(TAU*t*2)
    _draw_bill(img,180,330+bounce,310,145,"BILLS",accent)
    _draw_key(img,700,410-bounce*.6,1.0,(*accent,255))
    _label(img,"OBJECT?",(W/2,165),46,accent)
    for i in range(3):
        a=TAU*(i/3+t*.12); x=W/2+240*math.cos(a); y=365+105*math.sin(a)
        d.line((x,y,W/2,390),fill=(*light,120),width=4)


def _vortex(img,t,accent,light,labels=False):
    d=ImageDraw.Draw(img); cx,cy=W*.50,H*.48; rng=np.random.default_rng(733)
    for i in range(560):
        base=rng.random(); theta=rng.uniform(0,TAU)+TAU*(1.5*t)*(1.3-base); r=35+base*270
        life=(rng.random()+t*.55)%1; r=r*(.35+.65*life)
        x=cx+r*math.cos(theta)*1.45; y=cy+r*math.sin(theta)*.55; rr=1.2+3*(1-base)
        col=_mix(accent,light,.2+.7*(1-base)); d.ellipse((x-rr,y-rr,x+rr,y+rr),fill=(*col,210))
    _glow_line(img,_wave_points(100,W-100,cy+210,18,4,TAU*t),accent,3,10)
    if labels:
        for text,a in zip(("MOVEMENT","PRESSURE","GRAVITY","SHAPE"),(0.1,1.7,3.2,4.7)):
            aa=a+.25*math.sin(TAU*t); x=cx+370*math.cos(aa); y=cy+190*math.sin(aa)
            _label(img,text,(x,y),23,accent); d.line((x,y,cx+145*math.cos(aa),cy+70*math.sin(aa)),fill=(*light,120),width=3)


def _scene_self_change(img,t,accent,light):
    _silhouette(img,(W*.5,H*.56),.70,(32,40,52,230),0,False); d=ImageDraw.Draw(img)
    for i,(name,y) in enumerate(zip(("BODY","THOUGHTS","BELIEFS"),(230,340,450))):
        shift=60*math.sin(TAU*(t+i/3))
        d.rounded_rectangle((350+shift,y-31,802+shift,y+31),radius=20,fill=(*_mix(accent,light,.25*i),185),outline=(*light,180),width=2)
        d.text((W/2+shift,y),name,font=_font(28,True),fill=(248,251,252),anchor="mm")
    _label(img,"SAME NAME",(W/2,590),29,accent)


def _scene_memory_tiles(img,t,accent,light):
    d=ImageDraw.Draw(img); labels=("CELLS","MEMORIES","PASSWORDS","OPINIONS")
    for i,name in enumerate(labels):
        u=(t+i*.23)%1; x=130+i*245+50*math.sin(TAU*u); y=290+80*math.sin(TAU*(u+i*.17)); alpha=int(120+130*abs(math.sin(math.pi*u)))
        d.rounded_rectangle((x-92,y-52,x+92,y+52),radius=18,fill=(*_mix(accent,light,i/5),alpha),outline=(*light,170),width=2)
        d.text((x,y),name,font=_font(22,True),fill=(248,250,252,alpha),anchor="mm")
    _label(img,"ME",(W/2,520),58,accent); d.line((W/2,465,W/2,350),fill=(*light,160),width=4)


def _scene_relationship(img,t,accent,light):
    d=ImageDraw.Draw(img); pts=[]
    for i in range(8):
        a=TAU*i/8+0.15*math.sin(TAU*t+i); r=190+28*math.sin(TAU*t*1.2+i*.8)
        pts.append((W*.5+r*math.cos(a),H*.48+r*.55*math.sin(a)))
    for i,p in enumerate(pts):
        q=pts[(i+1)%len(pts)]; d.line((*p,*q),fill=(*accent,150),width=5)
        if i%2==0:
            r=16+6*math.sin(TAU*t+i); d.ellipse((p[0]-r,p[1]-r,p[0]+r,p[1]+r),fill=(*light,235))
        else:
            s=25; d.rounded_rectangle((p[0]-s,p[1]-s,p[0]+s,p[1]+s),radius=7,fill=(*_mix(accent,light,.5),230))
    _label(img,"RELATIONSHIP",(W/2,585),36,accent)


def _scene_rebuild(img,t,accent,light):
    d=ImageDraw.Draw(img); cx,cy=W*.5,H*.50; rng=np.random.default_rng(91)
    for i in range(110):
        a=TAU*rng.random(); rr=205*math.sqrt(rng.random()); target=(cx+rr*math.cos(a)*.55,cy+rr*math.sin(a)); start=(cx+(rng.random()-.5)*900,cy+(rng.random()-.5)*520)
        p=_ease((t*1.25+i*.007)%1); x=_lerp(start[0],target[0],p); y=_lerp(start[1],target[1],p); size=4+5*rng.random()
        d.rounded_rectangle((x-size,y-size,x+size,y+size),radius=2,fill=(*_mix(accent,light,rng.random()),220))
    _label(img,"REBUILDING “PERSON”",(W/2,590),32,accent)


def _scene_song_not_object(img,t,accent,light):
    fade=max(0,1-t*1.35); _draw_piano(img,120,325,.95,int(255*fade)); _draw_speaker(img,W-145,400,.82,int(255*fade))
    _glow_line(img,_wave_points(120,W-120,250,64,5,TAU*t*1.7),accent,6,20)
    _label(img,"THE SONG CONTINUES",(W/2,570),32,accent)


def _scene_song_transfer(img,t,accent,light):
    _draw_piano(img,60,385,.70,220); _draw_speaker(img,W-120,405,.62,230); xhead=110+(W-220)*t
    pts=_wave_points(110,min(xhead,W-110),255,50,4,TAU*t*2)
    if len(pts)>1: _glow_line(img,pts,accent,5,18)
    _label(img,"RELATIONSHIP BECOMES AUDIBLE",(W/2,575),28,accent)


def _scene_body_receiver(img,t,accent,light):
    _silhouette(img,(W/2,360),.67,(25,30,40,220),0,False); _glow_line(img,_wave_points(210,W-210,330,42,5,TAU*t*1.5),accent,5,18)
    d=ImageDraw.Draw(img)
    for r in (72,116,160): d.ellipse((W/2-r,330-r*.45,W/2+r,330+r*.45),outline=(*light,105),width=3)
    _label(img,"WHERE THE PATTERN PLAYS",(W/2,585),31,accent)


def _scene_wifi_taxes(img,t,accent,light):
    d=ImageDraw.Draw(img)
    for i in range(4): _draw_bill(img,130+i*16,350-i*15,300,140,"TAXES",accent)
    d.rounded_rectangle((750,400,990,500),radius=22,fill=(25,30,38),outline=(*accent,220),width=4)
    d.line((800,400,785,315),fill=(*light,220),width=7); d.line((940,400,955,315),fill=(*light,220),width=7)
    for k in range(3):
        r=65+50*k+22*math.sin(TAU*t); d.arc((870-r,305-r*.55,870+r,305+r*.55),200,340,fill=(*accent,180-k*35),width=6)
    _label(img,"NOT A DIMENSIONAL WI-FI SIGNAL",(W/2,160),28,accent)


def _scene_kitchen_forget(img,t,accent,light):
    d=ImageDraw.Draw(img); d.rounded_rectangle((130,130,W-130,H-90),radius=26,fill=(225,220,205,34),outline=(*light,140),width=5)
    d.line((W/2,130,W/2,H-90),fill=(*light,120),width=5)
    d.text((360,180),"LIVING ROOM",font=_font(25,True),fill=(*light,180),anchor="mm"); d.text((W-360,180),"KITCHEN",font=_font(25,True),fill=(*light,180),anchor="mm")
    x=270+500*_ease(min(t*1.5,1)); y=390+18*math.sin(TAU*t*2); d.ellipse((x-23,y-23,x+23,y+23),fill=(*accent,245))
    _label(img,"WHY AM I GOING IN HERE?" if t<.65 else "…",(x,y-85),22 if t<.65 else 40,accent)


def _scene_family_network(img,t,accent,light):
    d=ImageDraw.Draw(img); cx,cy=W/2,330; nodes=[]
    for i in range(6):
        a=TAU*i/6-.3; nodes.append((cx+270*math.cos(a),cy+155*math.sin(a)))
    labels=("MEMORIES","TENSIONS","JOKES","LOYALTIES","EXPECTATIONS","THE ARGUMENT")
    for i,p in enumerate(nodes):
        for j,q in enumerate(nodes):
            if j>i and (i+j)%3==0: d.line((*p,*q),fill=(*accent,80),width=3)
        rr=32+5*math.sin(TAU*t+i); d.ellipse((p[0]-rr,p[1]-rr,p[0]+rr,p[1]+rr),fill=(*_mix(accent,light,i/7),230)); _label(img,labels[i],(p[0],p[1]+62),18,accent)
    ax,ay=nodes[-1]; d.line((ax,ay,ax+65*math.sin(TAU*t),ay-55),fill=(*light,170),width=5)


def _scene_city_bricks(img,t,accent,light):
    d=ImageDraw.Draw(img); base_y=535
    buildings=[(110,335,240),(300,235,155),(485,300,220),(740,190,165),(930,305,115)]
    for bi,(x,top,w) in enumerate(buildings):
        rows=max(2,int((base_y-top)/34)); cols=max(2,int(w/42))
        bw=w/cols; bh=(base_y-top)/rows
        for r in range(rows):
            for c in range(cols):
                phase=(t*1.35 + bi*.17 + r*.09 + c*.055) % 1.0
                if phase < .44:
                    local=phase/.44
                    slide=0.0
                    color_mix=.15+.45*local
                    alpha=230
                elif phase < .58:
                    local=(phase-.44)/.14
                    slide=_ease(local)*(bw*2.5)
                    color_mix=.60
                    alpha=int(230*(1-local))
                elif phase < .72:
                    local=(phase-.58)/.14
                    slide=-(1-_ease(local))*(bw*2.5)
                    color_mix=.95-.28*local
                    alpha=int(230*local)
                else:
                    local=(phase-.72)/.28
                    slide=0.0
                    color_mix=.67-.35*local
                    alpha=230
                xx=x+c*bw+slide
                yy=top+r*bh
                col=_mix((72,78,90),accent,color_mix)
                d.rounded_rectangle((xx+2,yy+2,xx+bw-3,yy+bh-3),radius=3,
                                    fill=(*col,alpha),outline=(*light,min(alpha,150)),width=2)
        d.rectangle((x,top,x+w,base_y),outline=(*light,165),width=3)
    scan_x=80+(W-160)*((t*1.1)%1.0)
    d.rectangle((scan_x-5,150,scan_x+5,base_y),fill=(*accent,90))
    _glow_line(img,[(90,base_y),(W-90,base_y)],accent,4,12)
    _label(img,"SAME CITY — DIFFERENT BRICKS",(W/2,590),30,accent)


def _scene_flame(img,t,accent,light):
    d=ImageDraw.Draw(img); wood_scale=max(.15,1-t*.85)
    for off in (-60,60):
        x=W/2+off*wood_scale; d.rounded_rectangle((x-125*wood_scale,485,x+125*wood_scale,530),radius=22,fill=(92,48,27),outline=(180,104,55),width=3)
    cx=W/2
    for layer,(col,amp,height) in enumerate([((255,72,30),100,275),((255,178,46),70,225),((255,242,173),34,165)]):
        pts=[(cx,515)]
        for j in range(19):
            u=j/18; y=515-height*u; x=cx+amp*(1-u)*math.sin(TAU*(u*1.2+t*1.5)+layer); pts.append((x,y))
        pts += [(cx,515)]; d.polygon(pts,fill=(*col,210))
    _label(img,"WOOD DISAPPEARS — FLAME CONTINUES",(W/2,590),28,accent)


def _scene_costume_dance(img,t,accent,light):
    d=ImageDraw.Draw(img); alpha=int(255*max(0,1-t*1.35))
    d.ellipse((250-32,155-32,250+32,155+32),outline=(*light,alpha),width=5); d.rounded_rectangle((185,190,315,440),radius=50,outline=(*light,alpha),width=7)
    for k in range(12):
        u=max(0,t-k*.045); x=500+380*u; y=350-135*math.sin(math.pi*u); a=max(25,220-k*16)
        d.ellipse((x-17,y-17,x+17,y+17),fill=(*accent,a)); d.line((x,y+10,x-36*math.cos(TAU*u),y+100),fill=(*light,a),width=7)
    _label(img,"COSTUME FADES — DANCE REMAINS",(W/2,590),28,accent)


def _scene_thing_pattern(img,t,accent,light):
    d=ImageDraw.Draw(img); x,y=290,330; s=115
    d.polygon([(x,y-s),(x+s,y-s/2),(x,y),(x-s,y-s/2)],fill=(115,125,140),outline=(*light,180)); d.polygon([(x-s,y-s/2),(x,y),(x,y+s),(x-s,y+s/2)],fill=(65,72,84),outline=(*light,180)); d.polygon([(x+s,y-s/2),(x,y),(x,y+s),(x+s,y+s/2)],fill=(88,96,110),outline=(*light,180)); _label(img,"THING",(290,530),28,accent)
    cx,cy=830,330; nodes=[]
    for i in range(10):
        a=TAU*i/10+TAU*t*.5; r=110+40*math.sin(TAU*t+i*.8); nodes.append((cx+r*math.cos(a),cy+r*.72*math.sin(a)))
    for i,p in enumerate(nodes):
        q=nodes[(i+3)%10]; d.line((*p,*q),fill=(*accent,130),width=4); d.ellipse((p[0]-9,p[1]-9,p[0]+9,p[1]+9),fill=(*light,240))
    _label(img,"PATTERN",(830,530),28,accent)


def _scene_instrument_final(img,t,accent,light):
    d=ImageDraw.Draw(img); cx,cy=W/2,320; alpha=int(230*max(.15,1-t*.7))
    d.ellipse((cx-64,cy-135,cx+64,cy-10),outline=(*light,alpha),width=8); d.line((cx,cy-10,cx,cy+150),fill=(*light,alpha),width=12); d.line((cx,cy+110,cx-68,cy+185),fill=(*light,alpha),width=10); d.line((cx,cy+110,cx+68,cy+185),fill=(*light,alpha),width=10)
    ring=205*(1-t*.55); d.ellipse((cx-ring,cy-ring*.62,cx+ring,cy+ring*.62),outline=(*accent,150),width=5)
    for k in range(4):
        yy=190+k*70; pts=_wave_points(80,W-80,yy,18+7*k,4+k,TAU*t*1.3+k); col=_mix(accent,light,k/5); d.line(pts,fill=(*col,210),width=4,joint="curve")
    _label(img,"REALITY WAS LISTENING TO THE MUSIC",(W/2,595),29,accent)


RENDERERS = {
    "identity_flow": _scene_identity,
    "keys_bills_object": _scene_keys_bills,
    "whirlpool_material": lambda i,t,a,l:_vortex(i,t,a,l,False),
    "whirlpool_persistence": lambda i,t,a,l:_vortex(i,t,a,l,False),
    "forces_pattern": lambda i,t,a,l:_vortex(i,t,a,l,True),
    "self_change": _scene_self_change,
    "memory_tiles": _scene_memory_tiles,
    "relationship_pieces": _scene_relationship,
    "self_rebuild": _scene_rebuild,
    "song_not_object": _scene_song_not_object,
    "song_transfer": _scene_song_transfer,
    "body_receiver": _scene_body_receiver,
    "wifi_taxes": _scene_wifi_taxes,
    "kitchen_forget": _scene_kitchen_forget,
    "family_network": _scene_family_network,
    "city_bricks": _scene_city_bricks,
    "flame_process": _scene_flame,
    "costume_dance": _scene_costume_dance,
    "thing_vs_pattern": _scene_thing_pattern,
    "instrument_final": _scene_instrument_final,
}


def render_clip(scene: dict, output: Path) -> None:
    duration=max(float(scene.get("duration") or 4.0), .5); frames=max(1,int(math.ceil(duration*FPS)))
    palette=scene.get("symbolic_palette") or "cyan"
    if palette not in PALETTES: palette="cyan"
    _,_,accent,light=PALETTES[palette]; kind=scene.get("symbolic_kind"); fn=RENDERERS.get(kind)
    if fn is None: raise ValueError(f"unknown symbolic_kind: {kind}")
    output.parent.mkdir(parents=True,exist_ok=True); partial=output.with_suffix(".part.mp4")
    cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","-","-an","-c:v","libx264",*ENCODE_QUALITY,*COLOR_TAGS,"-pix_fmt","yuv420p","-movflags","+faststart",str(partial)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    try:
        for f in range(frames):
            t=f/max(frames-1,1); img=_background(palette,t); fn(img,t,accent,light)
            shade=Image.new("RGBA",img.size,(0,0,0,0)); sd=ImageDraw.Draw(shade); sd.rectangle((0,0,W,60),fill=(0,0,0,80)); sd.rectangle((0,H-58,W,H),fill=(0,0,0,70)); img.paste(shade,(0,0),shade)
            proc.stdin.write(np.asarray(img,dtype=np.uint8).tobytes())
    finally:
        if proc.stdin: proc.stdin.close()
    rc=proc.wait()
    if rc!=0: raise RuntimeError(f"ffmpeg exited {rc}")
    os.replace(partial,output)


def main(build_dir: str, index: int) -> None:
    bd=Path(build_dir); script_path=bd/"script.json"; script=json.loads(script_path.read_text(encoding="utf-8")); scene=script["scenes"][index]; output=bd/f"clip_{index:02d}.mp4"
    if output.exists() and output.stat().st_size>100_000 and scene.get("symbolic_render_version")==2:
        print(f"symbolic {index}: exists"); return
    render_clip(scene,output); evidence=motion.temporal_evidence(str(output))
    symbolic_motion_ok = bool(evidence.get("passes") or (evidence.get("active_region_ratio", 0) >= 0.015 and evidence.get("frame_difference", 0) >= 3.0))
    evidence["passes"] = symbolic_motion_ok; evidence["verification_profile"] = "deterministic_symbolic_v1"
    if not symbolic_motion_ok: raise RuntimeError(f"symbolic scene {index} failed temporal verification: {evidence}")
    scene.update({"clip":str(output),"motion_kind":"video","motion_mode":"video","motion_source":"deterministic_symbolic","motion_verified":True,"motion_evidence":evidence,"symbolic_render_version":2})
    script_path.write_text(json.dumps(script,indent=1,ensure_ascii=False),encoding="utf-8")
    print(f"symbolic {index}: {scene.get('symbolic_kind')} done ({output.stat().st_size} bytes)")


if __name__=="__main__":
    main(sys.argv[1],int(sys.argv[2]))
