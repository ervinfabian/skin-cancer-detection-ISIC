# -*- coding: utf-8 -*-
"""Use case diagram — derékszögű (ortogonális) vonalvezetés, kézi elrendezés."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, Rectangle, FancyArrowPatch, Circle

OUT = "/Users/ervin/Downloads/szakdolgozat/skin-cancer-detection-ISIC/docs/figures/uml"
C_FILL="#e0f2fe"; C_EDGE="#2563eb"; C_INK="#1f2933"; C_GREY="#64748b"
plt.rcParams.update({"font.family":"DejaVu Sans"})

fig, ax = plt.subplots(figsize=(13, 8))
ax.set_xlim(0,100); ax.set_ylim(2,68); ax.axis("off")

# rendszerhatár
ax.add_patch(Rectangle((20,3),78,63,fill=False,edgecolor=C_INK,lw=1.6))
ax.text(59,63.4,"Bőrelváltozás-szűrő rendszer",ha="center",va="center",
        fontsize=14,fontweight="bold",color=C_INK)

# aktor
ax.add_patch(Circle((8,42),1.6,fill=False,edgecolor=C_EDGE,lw=1.8))
ax.plot([8,8],[40.4,35],color=C_EDGE,lw=1.8)
ax.plot([5.4,10.6],[38.6,38.6],color=C_EDGE,lw=1.8)
ax.plot([8,5.4],[35,31],color=C_EDGE,lw=1.8)
ax.plot([8,10.6],[35,31],color=C_EDGE,lw=1.8)
ax.text(8,28.5,"Felhasználó",ha="center",va="center",fontsize=12.5,color=C_INK)

def uc(cx,cy,text,w=24,h=8.6,fs=12):
    ax.add_patch(Ellipse((cx,cy),w,h,facecolor=C_FILL,edgecolor=C_EDGE,lw=1.6,zorder=3))
    ax.text(cx,cy,text,ha="center",va="center",fontsize=fs,color=C_INK,zorder=4)
    return (cx,cy,w,h)

# fő use case-ek
MX=37
ys=[58,48,38,28,18,8]
labels=["Bejelentkezés\n(Google-fiók)","Kép feltöltése /\nfotó készítése",
        "Elváltozás elemzése","Kérdés feltevése\n(párbeszéd)",
        "Előzmények\nmegtekintése","Kijelentkezés"]
main=[uc(MX,y,t) for y,t in zip(ys,labels)]

# --- aktor → use case-ek: derékszögű busz ---
TRUNK=16.5
ax.plot([10.6,TRUNK],[38.6,38.6],color=C_INK,lw=1.3,zorder=1)     # aktor → trunk
ax.plot([TRUNK,TRUNK],[ys[-1],ys[0]],color=C_INK,lw=1.3,zorder=1) # függőleges trunk
for cx,cy,w,h in main:
    ax.plot([TRUNK,cx-w/2],[cy,cy],color=C_INK,lw=1.3,zorder=1)    # vízszintes ág

# --- «include» busz (derékszögű) ---
a_cx,a_cy,a_w,a_h = main[2]   # Elváltozás elemzése
ITRUNK=57
ax.text(78,57.5,"Az elemzés lépései",ha="center",va="center",
        fontsize=11.5,fontstyle="italic",color=C_GREY)
sub=[uc(78,50,"Természetes nyelvű\nmagyarázat",27,8.2,11.5),
     uc(78,38,"Rosszindulatúság-\nosztályozás",27,8.2,11.5),
     uc(78,26,"Képvalidáció",27,8.2,11.5)]
# vízszintes az analyze-ból a trunkig + függőleges trunk
ax.plot([a_cx+a_w/2,ITRUNK],[a_cy,a_cy],color=C_INK,lw=1.3,ls="--",zorder=1)
ax.plot([ITRUNK,ITRUNK],[sub[2][1],sub[0][1]],color=C_INK,lw=1.3,ls="--",zorder=1)
for cx,cy,w,h in sub:
    a=FancyArrowPatch((ITRUNK,cy),(cx-w/2,cy),arrowstyle="-|>",mutation_scale=13,
                      lw=1.3,color=C_INK,ls="--",zorder=1,shrinkA=0,shrinkB=2)
    ax.add_patch(a)
    ax.text((ITRUNK+cx-w/2)/2, cy+1.6, "«include»", ha="center",va="center",
            fontsize=10,fontstyle="italic",color=C_GREY,zorder=4,
            bbox=dict(boxstyle="round,pad=0.1",fc="white",ec="none"))

fig.savefig(f"{OUT}/usecase.png",dpi=200,bbox_inches="tight",facecolor="white")
fig.savefig(f"{OUT}/usecase.svg",bbox_inches="tight",facecolor="white")
plt.close(fig); print("OK usecase")
