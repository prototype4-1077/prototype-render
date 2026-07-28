"""Review sheet: chosen frame + top alternates for every scene, one image.
Usage: python3 altsheet.py <build_dir>   -> writes <build_dir>/alts_sheet.jpg"""
import glob, json, os, subprocess, sys
from PIL import Image, ImageDraw

from video_format import BAND_HEIGHT, BAND_WIDTH, BAND_Y


def main(bd):
    s = json.load(open(f"{bd}/script.json"))
    manifest = json.load(open(f"{bd}/alts.json")) if os.path.exists(f"{bd}/alts.json") else {}
    n = len(s["scenes"])
    TW, TH, COLS = 220, 124, 4  # chosen + up to 3 alts per row
    sheet = Image.new("RGB", (COLS * TW + 120, n * TH), "black")
    d = ImageDraw.Draw(sheet)
    for i in range(n):
        y = i * TH
        d.text((8, y + TH // 2 - 6), f"{i:02d}", fill="yellow")
        seg = f"{bd}/seg_{i:02d}.mp4"
        if os.path.exists(seg):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", seg,
                            "-frames:v", "1", "-vf",
                            f"crop={BAND_WIDTH}:{BAND_HEIGHT}:0:{BAND_Y},scale=220:124",
                            "/tmp/_alt.png"],
                           capture_output=True)
            try:
                sheet.paste(Image.open("/tmp/_alt.png"), (120, y))
                d.text((124, y + 2), "CHOSEN", fill="lime")
            except Exception:
                pass
        for k, alt in enumerate(manifest.get(str(i), [])[:3]):
            safe = str(alt["id"]).replace(":", "_")
            hits = glob.glob(f"{bd}/alts/{i:02d}_{k}_{safe}.jpg")
            if hits:
                im = Image.open(hits[0]).convert("RGB")
                im.thumbnail((TW, TH))
                x = 120 + (k + 1) * TW
                sheet.paste(im, (x, y))
                d.text((x + 4, y + 2), str(alt["id"])[:22], fill="white")
    sheet.save(f"{bd}/alts_sheet.jpg", quality=82)
    print(f"alts_sheet.jpg: {n} scenes")


if __name__ == "__main__":
    main(sys.argv[1])
