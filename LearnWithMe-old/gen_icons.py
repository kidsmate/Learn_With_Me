#!/usr/bin/env python3
"""生成安冉的学习助手应用图标 (PNG) - 仅使用内置库"""
import struct
import zlib

def create_png(width, height, pixels):
    """pixels: list of (r,g,b,a) tuples, row-major"""
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    raw = b''
    for y in range(height):
        raw += b'\x00'  # filter byte
        for x in range(width):
            r, g, b, a = pixels[y * width + x]
            raw += struct.pack('BBBB', r, g, b, a)

    compressed = zlib.compress(raw, 9)
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', compressed) + chunk(b'IEND', b'')

def make_icon(size):
    """生成一个圆形渐变背景 + 书本+幼苗图标的 PNG"""
    pixels = []
    cx = cy = size / 2
    r = size * 0.46
    
    # 颜色
    bg1 = (108, 92, 231)   # #6C5CE7
    bg2 = (162, 155, 254)  # #A29BFE
    white = (255, 255, 255)
    
    for y in range(size):
        for x in range(size):
            dx = x - cx
            dy = y - cy
            dist = (dx*dx + dy*dy) ** 0.5
            
            if dist <= r:
                # 在圆内，渐变背景
                t = dist / r
                R = int(bg1[0] + (bg2[0] - bg1[0]) * t)
                G = int(bg1[1] + (bg2[1] - bg1[1]) * t)
                B = int(bg1[2] + (bg2[2] - bg1[2]) * t)
                a = 255
                
                # 画书本图标 (居中的白色书本)
                # 书本主体
                book_w = size * 0.36
                book_h = size * 0.28
                book_x = cx - book_w / 2
                book_y = cy - book_h / 2 + size * 0.04
                
                # 书本左页
                if book_x <= x <= cx - size*0.01 and book_y <= y <= book_y + book_h:
                    R, G, B = 255, 255, 255
                # 书本右页
                if cx + size*0.01 <= x <= book_x + book_w and book_y <= y <= book_y + book_h:
                    R, G, B = 245, 245, 255
                # 书脊
                if cx - size*0.01 <= x <= cx + size*0.01 and book_y <= y <= book_y + book_h:
                    R, G, B = bg1[0], bg1[1], bg1[2]
                
                # 画幼苗 (🌱) - 在书本上方
                sprout_cx = cx
                sprout_cy = book_y - size * 0.04
                # 茎
                if abs(x - sprout_cx) <= size*0.012 and sprout_cy - size*0.08 <= y <= sprout_cy + size*0.02:
                    R, G, B = 0, 184, 148  # 绿色
                # 左叶
                leaf_dx = x - (sprout_cx - size*0.04)
                leaf_dy = y - (sprout_cy - size*0.06)
                if (leaf_dx**2/(size*0.04)**2 + leaf_dy**2/(size*0.025)**2) <= 1:
                    R, G, B = 0, 184, 148
                # 右叶
                leaf_dx = x - (sprout_cx + size*0.04)
                leaf_dy = y - (sprout_cy - size*0.06)
                if (leaf_dx**2/(size*0.04)**2 + leaf_dy**2/(size*0.025)**2) <= 1:
                    R, G, B = 0, 184, 148
                
                # 边缘抗锯齿
                edge = r - dist
                if edge < 1.5:
                    a = int(255 * edge / 1.5) if edge > 0 else 0
                
                pixels.append((R, G, B, a))
            else:
                # 圆外透明
                pixels.append((0, 0, 0, 0))
    
    return create_png(size, size, pixels)

# 生成图标
for s in [192, 512]:
    data = make_icon(s)
    with open(f'/workspace/anran-learning/icons/icon-{s}.png', 'wb') as f:
        f.write(data)
    print(f'Generated icon-{s}.png ({len(data)} bytes)')

print('Done!')
