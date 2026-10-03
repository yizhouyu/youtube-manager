"""Photo retouch for thumbnail hero frames (creator, 2026-10-03: run every cover photo through this first).

Use style "natural" (the creator's pick) on every hero frame before adding text. The steps:
- tone curve: lift the shadows, recover the highlights;
- clarity: large-radius local contrast;
- light dehaze;
- vibrance;
- graduated sky;
- warm / teal split tone;
- soft vignette;
- final unsharp mask.

    from src.thumbnail_generator.retouch import retouch
    retouch(Image.open(frame), "natural").save(out)
"""
import numpy as np
from PIL import Image, ImageFilter
def to(a): return np.clip(a,0,1)
def retouch(im, style="natural"):
    a=np.asarray(im.convert('RGB')).astype(np.float32)/255
    lum=(0.299*a[...,0]+0.587*a[...,1]+0.114*a[...,2])[...,None]
    # 1) shadows lift / highlights recover (tone curve on luminance)
    sh=0.22 if style=="natural" else 0.28; hl=0.25 if style=="natural" else 0.3
    newl=lum+sh*(1-lum)**3*lum*3 - hl*lum**4*(1-lum)*3
    a=to(a*(newl/np.maximum(lum,1e-4)))
    # 2) local contrast / clarity (large-radius unsharp)
    im2=Image.fromarray((a*255).astype(np.uint8))
    blur=np.asarray(im2.filter(ImageFilter.GaussianBlur(40))).astype(np.float32)/255
    k=0.35 if style=="natural" else 0.5
    a=to(a+k*(a-blur))
    # 3) dehaze: subtract a bit of the dark channel haze
    dark=a.min(axis=2,keepdims=True); a=to((a-0.06*dark)/(1-0.06))
    # 4) vibrance: boost low-saturation pixels more
    mx=a.max(axis=2,keepdims=True); mn=a.min(axis=2,keepdims=True); sat=(mx-mn)
    v=0.35 if style=="natural" else 0.55
    lum=(0.299*a[...,0]+0.587*a[...,1]+0.114*a[...,2])[...,None]
    a=to(lum+(a-lum)*(1+v*(1-sat)))
    # 5) sky: gently deepen the top third (graduated filter)
    h=a.shape[0]; g=np.linspace(1,0,h)[:,None,None]; g=np.clip((g-0.55)/0.45,0,1)
    a=to(a*(1-0.12*g)+np.array([0.0,0.01,0.03])*g)
    # 6) warmth + slight teal in shadows (cinematic split tone)
    lum=(0.299*a[...,0]+0.587*a[...,1]+0.114*a[...,2])[...,None]
    warm=np.array([0.03,0.012,-0.02]) if style=="natural" else np.array([0.045,0.018,-0.03])
    teal=np.array([-0.015,0.005,0.02])
    a=to(a+warm*lum+teal*(1-lum)*0.6)
    # 7) vignette
    H,W=a.shape[:2]; y,x=np.ogrid[:H,:W]; r=np.sqrt(((x-W/2)/(W/2))**2+((y-H/2)/(H/2))**2)
    a=to(a*(1-0.18*np.clip(r-0.6,0,1)[...,None]))
    out=Image.fromarray((a*255).astype(np.uint8))
    return out.filter(ImageFilter.UnsharpMask(radius=2,percent=60,threshold=2))
