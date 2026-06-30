# -*- coding: utf-8 -*-
"""Komponens-diagram — kézi elrendezés, derékszögű vonalvezetés, átfedés nélkül."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

OUT = "/Users/ervin/Downloads/szakdolgozat/skin-cancer-detection-ISIC/docs/figures/uml"
INK="#1f2933"; GREY="#64748b"
BL_F="#e0f2fe"; BL_E="#2563eb"
PU_F="#ede9fe"; PU_E="#7c3aed"
OR_F="#fff7ed"; OR_E="#ea580c"
plt.rcParams.update({"font.family":"DejaVu Sans"})

fig, ax = plt.subplots(figsize=(13.5, 7.2))
ax.set_xlim(0,100); ax.set_ylim(0,62); ax.axis("off")

def comp(x,y,w,h,text,fc,ec,fs=11,bold=False):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.02,rounding_size=0.6",
                 linewidth=1.6,edgecolor=ec,facecolor=fc,zorder=3))
    ix,iy=x+w-3.2,y+h-2.4
    ax.add_patch(Rectangle((ix,iy),2.4,1.5,fill=True,facecolor="white",edgecolor=ec,lw=1,zorder=4))
    ax.add_patch(Rectangle((ix-0.7,iy+0.3),1.0,0.4,fill=True,facecolor="white",edgecolor=ec,lw=0.8,zorder=5))
    ax.add_patch(Rectangle((ix-0.7,iy+0.8),1.0,0.4,fill=True,facecolor="white",edgecolor=ec,lw=0.8,zorder=5))
    ax.text(x+w/2,y+h/2,text,ha="center",va="center",fontsize=fs,color=INK,
            fontweight="bold" if bold else "normal",zorder=4)
    return (x,y,w,h)

def container(x,y,w,h,title):
    ax.add_patch(Rectangle((x,y),w,h,fill=False,edgecolor=GREY,lw=1.3,
                 linestyle=(0,(6,3)),zorder=1))
    ax.text(x+1.6,y+h-2,title,ha="left",va="center",fontsize=10.5,
            fontweight="bold",color=GREY,zorder=2)

def orth(points,label=None,lx=None,ly=None,dashed=False):
    xs=[p[0] for p in points]; ys=[p[1] for p in points]
    ax.plot(xs,ys,color=INK,lw=1.3,ls="--" if dashed else "-",zorder=2,
            solid_capstyle="round")
    ax.annotate("",xy=points[-1],xytext=points[-2],zorder=2,
                arrowprops=dict(arrowstyle="-|>",color=INK,lw=1.3,shrinkA=0,shrinkB=1))
    if label:
        ax.text(lx,ly,label,ha="center",va="center",fontsize=9.3,color=GREY,zorder=6,
                bbox=dict(boxstyle="round,pad=0.12",fc="white",ec="none"))

# ---- konténerek + komponensek ----
container(5,30,26,27,"KLIENSEK")
comp(8,45,20,8,"Android\n(Kotlin, MVVM)",BL_F,BL_E)
comp(8,33,20,8,"Webes felület\n(HTML / JS)",BL_F,BL_E)

container(40,30,42,27,"BACKEND")
comp(43,45,18,8,"Flask\nbackend",BL_F,BL_E)
comp(43,33,18,8,"FastAPI\nbackend",BL_F,BL_E)
comp(66,39,12,9,"MCP-\nszerver",BL_F,BL_E,bold=True)

ax.text(92.5,49.5,"GPU-szerver",ha="center",va="center",fontsize=10.5,fontweight="bold",color=PU_E)
comp(85,39.5,14,8,"ViT modell",PU_F,PU_E,fs=10.5,bold=True)
comp(80,7,18,8,"Gemini 2.5 Flash",OR_F,OR_E,fs=10.5)
comp(5,6,53,8.5,"Firebase  —  Auth · Firestore · Storage",OR_F,OR_E,fs=10.5,bold=True)

# csúcsok: AND c(18,49) WEB c(18,37) FL c(52,49) FA c(52,37) MCP c(72,43.5)
# VIT left(85,43.5) GEM top(89,15) left(80,11) FB top y=14.5
# ---- élek ----
orth([(28,49),(43,49)],"REST + SSE",35.5,50.5)                  # Android → Flask
orth([(28,37),(43,37)],"REST + SSE",35.5,38.5)                  # Web → FastAPI
orth([(61,49),(64,49),(64,45),(66,45)],"JSON-RPC 2.0",72,51)    # Flask → MCP
orth([(61,37),(64,37),(64,42),(66,42)])                         # FastAPI → MCP
orth([(78,43.5),(85,43.5)],"HTTP",81.5,45)                      # MCP → ViT
orth([(52,33),(52,17),(89,17),(89,15)],"HTTPS",70,18.6)         # backend → Gemini
orth([(45,33),(45,14.5)],"adat",47,23)                          # backend → Firebase
orth([(18,33),(18,14.5)],"hitelesítés",20.5,23)                # kliensek → Firebase

fig.savefig(f"{OUT}/component.png",dpi=200,bbox_inches="tight",facecolor="white")
fig.savefig(f"{OUT}/component.svg",bbox_inches="tight",facecolor="white")
plt.close(fig); print("OK component")
