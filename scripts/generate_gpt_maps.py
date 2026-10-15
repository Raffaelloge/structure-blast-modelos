#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, math, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'modelos'
OUT.mkdir(exist_ok=True)
AUTHOR = 'gpt da resenha'

CUBE_POS=[-.5,-.5,-.5,.5,-.5,-.5,.5,.5,-.5,-.5,.5,-.5,-.5,-.5,.5,.5,-.5,.5,.5,.5,.5,-.5,.5,.5]
CUBE_IDX=[0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,3,7,6,3,6,2,1,2,6,1,6,5,0,4,7,0,7,3]
RAMP_POS=[-.5,-.5,-.5,.5,-.5,-.5,-.5,-.5,.5,.5,-.5,.5,-.5,.5,.5,.5,.5,.5]
RAMP_IDX=[0,3,1,0,2,3,2,4,5,2,5,3,0,1,5,0,5,4,0,4,2,1,3,5]
PALETTE={'concrete':[.45,.47,.50,1],'dark':[.08,.10,.13,1],'steel':[.18,.23,.28,1],'yellow':[.95,.65,.06,1],'orange':[.95,.32,.08,1],'red':[.72,.08,.08,1],'blue':[.08,.30,.65,1],'cyan':[.05,.65,.75,1],'green':[.08,.50,.25,1],'white':[.80,.82,.84,1],'purple':[.40,.15,.60,1],'sand':[.62,.52,.34,1]}


def box(n,m,x,y,z,sx,sy,sz): n.append(('cube',m,(x,y,z),(sx,sy,sz),None))
def ramp(n,m,x,y,z,sx,sy,sz,rev=False): n.append(('ramp',m,(x,y,z),(sx,sy,sz),(0,1,0,0) if rev else None))


def make_glb(slug,name,desc,specs):
    buf=bytearray(); bvs=[]; acc=[]; meshes=[]; mats=[]; mesh_ids={}
    names=list(PALETTE)
    for mn,rgba in PALETTE.items():
        mats.append({'name':mn,'pbrMetallicRoughness':{'baseColorFactor':rgba,'metallicFactor':.15 if mn in ('steel','dark') else 0,'roughnessFactor':.7}})
    mid={n:i for i,n in enumerate(names)}
    def add_geom(pos,idx):
        while len(buf)%4: buf.append(0)
        po=len(buf); pb=struct.pack('<'+'f'*len(pos),*pos); buf.extend(pb)
        bvs.append({'buffer':0,'byteOffset':po,'byteLength':len(pb),'target':34962}); pbi=len(bvs)-1
        xs,ys,zs=pos[0::3],pos[1::3],pos[2::3]
        acc.append({'bufferView':pbi,'componentType':5126,'count':len(pos)//3,'type':'VEC3','min':[min(xs),min(ys),min(zs)],'max':[max(xs),max(ys),max(zs)]}); pa=len(acc)-1
        while len(buf)%4: buf.append(0)
        io=len(buf); ib=struct.pack('<'+'H'*len(idx),*idx); buf.extend(ib)
        bvs.append({'buffer':0,'byteOffset':io,'byteLength':len(ib),'target':34963}); ibi=len(bvs)-1
        acc.append({'bufferView':ibi,'componentType':5123,'count':len(idx),'type':'SCALAR','min':[min(idx)],'max':[max(idx)]}); ia=len(acc)-1
        return pa,ia
    geom={'cube':add_geom(CUBE_POS,CUBE_IDX),'ramp':add_geom(RAMP_POS,RAMP_IDX)}
    for g in ('cube','ramp'):
        for mn in names:
            pa,ia=geom[g]; mesh_ids[(g,mn)]=len(meshes)
            meshes.append({'name':f'{g}-{mn}','primitives':[{'attributes':{'POSITION':pa},'indices':ia,'material':mid[mn]}]})
    nodes=[]
    for i,(g,m,tr,sc,rot) in enumerate(specs):
        node={'name':f'{name}-{i:03d}','mesh':mesh_ids[(g,m)],'translation':[float(v) for v in tr],'scale':[float(v) for v in sc]}
        if rot: node['rotation']=[float(v) for v in rot]
        nodes.append(node)
    doc={'asset':{'version':'2.0','generator':'gpt da resenha map forge'},'scene':0,'scenes':[{'name':name,'nodes':list(range(len(nodes)))}],'nodes':nodes,'meshes':meshes,'materials':mats,'buffers':[{'byteLength':len(buf)}],'bufferViews':bvs,'accessors':acc,'extras':{'name':name,'author':AUTHOR,'description':desc}}
    jb=json.dumps(doc,separators=(',',':'),ensure_ascii=False).encode(); jb+=b' '*((-len(jb))%4)
    while len(buf)%4: buf.append(0)
    total=12+8+len(jb)+8+len(buf)
    data=struct.pack('<4sII',b'glTF',2,total)+struct.pack('<II',len(jb),0x4E4F534A)+jb+struct.pack('<II',len(buf),0x004E4942)+bytes(buf)
    target=OUT/f'gpt-{slug}.glb'; target.write_bytes(data)
    print(f'{target.name}: {len(specs)} peças · {len(data)/1024:.1f} KB · {hashlib.sha256(data).hexdigest()[:10]}')


def build_maps():
    maps=[]
    n=[]; box(n,'concrete',0,-.5,0,50,1,50)
    for x in range(-20,21,10): box(n,'steel',x,1.5,-22,8,3,2); box(n,'steel',x,1.5,22,8,3,2)
    for z in range(-12,13,8): box(n,'steel',-24,1.5,z,2,3,7); box(n,'steel',24,1.5,z,2,3,7)
    cols=['blue','red','yellow','green','orange']
    for i,(x,z) in enumerate([(-14,-12),(-4,-12),(8,-12),(15,-5),(-14,4),(-4,6),(7,5),(15,13),(-12,14),(1,16)]):
        for lv in range(1+i%3): box(n,cols[i%5],x,1.3+2.6*lv,z,6,2.4,2.5)
    ramp(n,'yellow',-2,1,0,5,2,8); ramp(n,'yellow',13,1,3,5,2,8,True)
    maps.append(('arena-de-containers','Arena de Containers','Arena industrial com contêineres empilhados, barreiras e rampas para destruição.',n))

    n=[]; box(n,'concrete',0,-.5,0,34,1,34)
    for lv in range(7):
        y=.45+lv*3.1; ox=(lv%2)*1.5-.75; oz=((lv+1)%2)*1.2-.6; box(n,'concrete',ox,y,oz,15,.6,15)
        for x in (-6,6):
            for z in (-6,6): box(n,'steel',x+ox,y+1.5,z+oz,.7,3,.7)
        box(n,['yellow','orange','blue'][lv%3],ox+8.5,y,oz,3,.5,6)
    box(n,'red',0,23,0,4,4,4); maps.append(('torre-maluca','Torre Maluca','Torre de sete pavimentos deslocados, pilares finos e balanços para derrubar.',n))

    n=[]; box(n,'concrete',0,-.5,0,60,1,45)
    for x in range(-24,25,8):
        for z in (-14,14): box(n,'steel',x,3,z,.7,6,.7)
        box(n,'steel',x,6,0,.7,.7,29)
    for x in range(-20,21,8): box(n,'yellow',x,.8,-5,5,1.6,2)
    for x in (-18,0,18): box(n,'orange',x,2.5,8,4,5,4)
    ramp(n,'yellow',-12,.8,18,7,1.6,7); ramp(n,'yellow',12,.8,18,7,1.6,7)
    maps.append(('patio-industrial','Pátio Industrial','Galpão aberto com pórticos, máquinas, tanques e docas.',n))

    n=[]; box(n,'sand',0,-1,0,70,1,28)
    for x in (-24,-12,0,12,24): box(n,'concrete',x,2,0,2,6,5)
    for x in range(-30,31,4): box(n,'concrete',x,5.3,0,3.8,.6,9)
    for x in range(-30,31,5):
        for z in (-4.5,4.5): box(n,'steel',x,6.2,z,.25,1.8,.25)
    for x in (-8,0,8): box(n,'yellow',x,9,0,.5,7,.5)
    box(n,'yellow',0,12,0,18,.5,.5); maps.append(('ponte-do-caos','Ponte do Caos','Ponte segmentada sobre pilares com tabuleiro destrutível e estrutura superior.',n))

    n=[]; box(n,'concrete',0,-.5,0,46,1,46)
    for x in range(-18,19,6):
        for k,z in enumerate(range(-18,19,6)):
            if (x//6+z//6)%3!=0:
                box(n,'white',x,1.5,z,.7,3,5) if (k+x//6)%2==0 else box(n,'white',x,1.5,z,5,3,.7)
    box(n,'yellow',0,3,0,3,6,3); maps.append(('labirinto-de-concreto','Labirinto de Concreto','Labirinto destrutível de paredes baixas com uma torre amarela no centro.',n))

    n=[]; box(n,'sand',0,-.5,0,55,1,55)
    for x in range(-16,17,4):
        for z in (-16,16): box(n,'concrete',x,2,z,3.8,4,2)
    for z in range(-12,13,4):
        for x in (-16,16): box(n,'concrete',x,2,z,2,4,3.8)
    for x in (-16,16):
        for z in (-16,16):
            for lv in range(3): box(n,'white',x,2+4*lv,z,5,3.8,5)
    for x in (-4,4): box(n,'concrete',x,3,16,4,6,2)
    box(n,'red',0,7,16,12,2,2); maps.append(('castelo-de-blocos','Castelo de Blocos','Castelo modular com muralhas segmentadas, quatro torres e portão destrutível.',n))

    n=[]; box(n,'concrete',0,-.5,0,50,1,40)
    for lv in range(5):
        y=.4+lv*3; box(n,'concrete',0,y,0,34,.5,28)
        for x in (-14,-7,0,7,14):
            for z in (-11,11): box(n,'steel',x,y+1.5,z,.5,3,.5)
    for lv in range(4):
        y=1.9+lv*3; side=-1 if lv%2==0 else 1; ramp(n,'yellow',side*12,y,0,7,3,16,side>0)
    maps.append(('estacionamento-vertical','Estacionamento Vertical','Garagem de cinco níveis com lajes, pilares e rampas laterais.',n))

    n=[]; box(n,'sand',0,-.5,0,60,1,50)
    for x in (-16,-8,0,8,16):
        for z in (-10,0,10): box(n,'steel',x,3,z,.6,6,.6)
    for y in (3,6):
        for x in (-16,-8,0,8,16): box(n,'steel',x,y,0,.5,.5,21)
    box(n,'yellow',22,8,-12,1.5,16,1.5); box(n,'yellow',10,16,-12,25,.8,.8); box(n,'yellow',22,17,-12,3,2,3)
    for i,x in enumerate(range(-18,19,6)): box(n,'orange' if i%2 else 'concrete',x,.6,17,4,1.2,4)
    maps.append(('canteiro-da-resenha','Canteiro da Resenha','Canteiro com estrutura metálica em obra, grua e pilhas de material.',n))

    n=[]; box(n,'blue',0,-2,0,65,1,65)
    for i,(x,z) in enumerate([(-18,-16),(16,-15),(-14,16),(17,17),(0,0)]):
        box(n,'sand',x,-.5,z,13,2,13)
        for lv in range(3+i):
            s=max(3,8-lv*.7); box(n,['white','cyan','yellow','orange','purple'][i],x,1.2+2.4*lv,z,s,2.2,s)
    box(n,'steel',-9,1,-8,12,.5,2); box(n,'steel',8,1,-8,12,.5,2); box(n,'steel',-7,1,8,2,.5,12); box(n,'steel',8,1,9,2,.5,12)
    maps.append(('ilhas-das-torres','Ilhas das Torres','Cinco ilhas conectadas por passarelas, cada uma com uma torre destrutível.',n))

    n=[]; box(n,'concrete',0,-.5,0,58,1,58)
    for i in range(24):
        a=i*2*math.pi/24; box(n,'dark',25*math.cos(a),1.5,25*math.sin(a),4,3,4)
    for x,z in [(-10,-10),(10,-10),(-10,10),(10,10),(0,-14),(0,14),(-14,0),(14,0)]: ramp(n,'yellow',x,1,z,5,2,7,(x+z)>0)
    for x,z in [(-6,0),(6,0),(0,-6),(0,6)]: box(n,'red',x,1.5,z,4,3,4)
    box(n,'orange',0,3,0,5,6,5); maps.append(('arena-demolicao','Arena de Demolição','Arena circular com rampas, blocos de impacto e torre central.',n))
    return maps


def patch_metadata_reader():
    p=ROOT/'scripts/sync_direct_glb.py'; s=p.read_text(encoding='utf-8')
    if 'def embedded_metadata(' not in s:
        s=s.replace('import json\n', 'import json\nimport struct\n')
        marker='def load_catalog() -> dict:\n'
        helper='''def embedded_metadata(path: Path) -> dict:\n    try:\n        data = path.read_bytes()\n        size, kind = struct.unpack_from("<II", data, 12)\n        if kind != 0x4E4F534A:\n            return {}\n        document = json.loads(data[20:20+size])\n        extras = document.get("extras", {})\n        return extras if isinstance(extras, dict) else {}\n    except Exception:\n        return {}\n\n\n'''
        s=s.replace(marker,helper+marker)
        s=s.replace('        old = previous_direct.get(relative, {})\n        entry = {', '        old = previous_direct.get(relative, {})\n        embedded = embedded_metadata(path)\n        entry = {')
        s=s.replace('            "name": old.get("name") or path.stem,\n            "author": old.get("author", ""),\n            "description": old.get("description", "GLB enviado diretamente para a biblioteca."),', '            "name": old.get("name") or embedded.get("name") or path.stem,\n            "author": old.get("author") or embedded.get("author", ""),\n            "description": old.get("description") or embedded.get("description") or "GLB enviado diretamente para a biblioteca.",')
        p.write_text(s,encoding='utf-8')
        print('Indexador de GLB direto atualizado para ler metadados embutidos.')


def main():
    patch_metadata_reader()
    for slug,name,desc,specs in build_maps(): make_glb(slug,name,desc,specs)
    print('10 mapas GPT gerados.')

if __name__=='__main__': main()
