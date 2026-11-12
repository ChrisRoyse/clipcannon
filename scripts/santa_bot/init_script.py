"""Chrome init script that intercepts getUserMedia for the Santa avatar camera/mic.

Moved verbatim from launch_browser() in scripts/santa_meet_bot.py.
"""

AVATAR_INIT_SCRIPT = """
        Object.defineProperty(navigator,"webdriver",{get:()=>false});
        const _origGUM=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        window.__santaJpegB64=null;
        navigator.mediaDevices.getUserMedia=async function(c){
            if(!c||!c.video) return _origGUM(c);
            try{
                // Step 1: Get REAL fake-device stream (has proper camera metadata)
                const realStream=await _origGUM({video:c.video});
                const realTrack=realStream.getVideoTracks()[0];
                const realSettings=realTrack.getSettings();
                const realCaps=realTrack.getCapabilities?realTrack.getCapabilities():{};
                const W=realSettings.width||1280, H=realSettings.height||720;
                console.log('[AvatarCam] Real track:',realTrack.label,W+'x'+H,JSON.stringify(realSettings));

                // Step 2: Canvas for rendering our frames
                const oc=new OffscreenCanvas(W,H);
                const ox=oc.getContext('2d');

                // Step 3: Try Insertable Streams approach
                let outTrack;
                if(typeof MediaStreamTrackProcessor!=='undefined'&&typeof MediaStreamTrackGenerator!=='undefined'){
                    console.log('[AvatarCam] Using Insertable Streams (Processor→Generator)');
                    const proc=new MediaStreamTrackProcessor({track:realTrack});
                    const gen=new MediaStreamTrackGenerator({kind:'video'});
                    const reader=proc.readable.getReader();
                    const writer=gen.writable.getWriter();
                    let imgReady=false;
                    const img=new Image();
                    img.onload=()=>{imgReady=true;};
                    // Background: decode JPEGs as they arrive (non-blocking)
                    let lastJpeg=null;
                    setInterval(()=>{
                        if(window.__santaJpegB64&&window.__santaJpegB64!==lastJpeg){
                            lastJpeg=window.__santaJpegB64;
                            img.src='data:image/jpeg;base64,'+lastJpeg;
                        }
                    },30);
                    // Frame pump: runs at fake device rate (~30fps), NEVER blocks
                    (async()=>{
                        while(true){
                            const{value:frame,done}=await reader.read();
                            if(done)break;
                            frame.close();
                            // Draw current image (already decoded, instant)
                            if(imgReady){
                                ox.drawImage(img,0,0,W,H);
                            }else{
                                ox.fillStyle='#1a1a2e';ox.fillRect(0,0,W,H);
                                ox.fillStyle='#eee';ox.font='36px Arial';
                                ox.fillText('Santa joining...',W/2-120,H/2);
                            }
                            const bmp=oc.transferToImageBitmap();
                            const vf=new VideoFrame(bmp,{timestamp:performance.now()*1000});
                            try{await writer.write(vf);}catch(e){vf.close();break;}
                            vf.close();
                        }
                    })();
                    // Spoof metadata on the generator track
                    const origGS=gen.getSettings.bind(gen);
                    gen.getSettings=()=>({...origGS(),...realSettings});
                    if(gen.getCapabilities)gen.getCapabilities=()=>realCaps;
                    outTrack=gen;
                }else{
                    // Fallback: canvas.captureStream + metadata spoofing
                    console.log('[AvatarCam] Fallback: captureStream + metadata spoof');
                    const visCanvas=document.createElement('canvas');
                    visCanvas.width=W;visCanvas.height=H;
                    const vx=visCanvas.getContext('2d');
                    const capStream=visCanvas.captureStream(15);
                    const capTrack=capStream.getVideoTracks()[0];
                    // Spoof metadata from real track
                    capTrack.getSettings=()=>realSettings;
                    if(realTrack.getCapabilities)capTrack.getCapabilities=()=>realCaps;
                    capTrack.getConstraints=()=>realTrack.getConstraints();
                    // Render loop on visible canvas
                    let lastJpeg=null;
                    (async()=>{
                        while(capTrack.readyState==='live'){
                            if(window.__santaJpegB64&&window.__santaJpegB64!==lastJpeg){
                                lastJpeg=window.__santaJpegB64;
                                try{
                                    const resp=await fetch('data:image/jpeg;base64,'+lastJpeg);
                                    const blob=await resp.blob();
                                    const bmp=await createImageBitmap(blob);
                                    vx.drawImage(bmp,0,0,W,H);
                                    bmp.close();
                                }catch(e){}
                            }else if(!lastJpeg){
                                vx.fillStyle='#1a1a2e';vx.fillRect(0,0,W,H);
                                vx.fillStyle='#eee';vx.font='36px Arial';
                                vx.fillText('Santa joining...',W/2-120,H/2);
                            }
                            await new Promise(r=>setTimeout(r,66));
                        }
                    })();
                    outTrack=capTrack;
                    realTrack.stop(); // free the real device
                }

                // Step 4: Build output stream
                const outStream=new MediaStream([outTrack]);

                // Step 5: Audio — get from fake device or create silent AudioContext
                if(c.audio){
                    try{
                        const aStream=await _origGUM({audio:c.audio});
                        for(const t of aStream.getAudioTracks())outStream.addTrack(t);
                    }catch(e){}
                    // Always create AudioContext for TTS injection
                    const actx=new AudioContext({sampleRate:48000});
                    const dest=actx.createMediaStreamDestination();
                    // If no audio track was added, add silent one
                    if(!outStream.getAudioTracks().length){
                        outStream.addTrack(dest.stream.getAudioTracks()[0]);
                    }
                    window.__santaAudioCtx=actx;
                    window.__santaAudioDest=dest;
                }
                console.log('[AvatarCam] Output stream:',outStream.getTracks().length,'tracks');
                console.log('[AvatarCam] Video settings:',JSON.stringify(outTrack.getSettings()));
                return outStream;
            }catch(e){
                console.error('[AvatarCam] Init failed, raw fallback:',e);
                return _origGUM(c);
            }
        };
        window.__santaPlayAudio=function(b64,sr){
            const ctx=window.__santaAudioCtx,dest=window.__santaAudioDest;
            if(!ctx||!dest)return Promise.resolve(false);
            return ctx.resume().then(()=>new Promise((res,rej)=>{
                try{
                    const bin=atob(b64),bytes=new Uint8Array(bin.length);
                    for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
                    const f32=new Float32Array(bytes.buffer);
                    const buf=ctx.createBuffer(1,f32.length,sr);
                    buf.copyToChannel(f32,0);
                    const src=ctx.createBufferSource();src.buffer=buf;
                    const g=ctx.createGain();g.gain.value=3.0;
                    src.connect(g);g.connect(dest);
                    src.onended=()=>res(true);src.start();
                }catch(e){rej(e.message);}
            }));
        };
    """
