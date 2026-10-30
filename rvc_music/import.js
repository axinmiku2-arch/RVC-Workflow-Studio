() => {
    const root = document.querySelector('gradio-app')?.shadowRoot || document;
    const surface = root.querySelector('#rvc-source-audio');
    if (!surface || surface.dataset.musicImportBound) return [];
    surface.dataset.musicImportBound = 'true';
    const supported = new Set(['ncm','qmc0','qmc3','qmcflac','qmcogg','tkm','bkcmp3','bkcflac','mflac','mgg','tm0','tm2','tm3','tm6']);
    const unsupported = new Set(['qmc','qmc2','qmc6','mflac0','mgg0','mgg1','mggl','kgm','kgma','vpr','kwm','xm','ofl_en']);
    let busy = false, worker = null, ticket = '', timeout = null;
    const status = () => root.querySelector('#music-import-status');
    const message = (text, state='busy') => {
        const node = status();
        if (node) { node.textContent=text; node.dataset.state=state; node.dataset.ticket=''; }
    };
    const finish = () => {
        busy=false; surface.dataset.importBusy='false'; clearTimeout(timeout);
        if (worker) { worker.terminate(); worker=null; }
    };
    const clearDownload = () => {
        const node=root.querySelector('#music-import-download');
        if (node) node.style.display='none';
    };
    const resetPlayer = () => {
        const clear=surface.querySelector('button[aria-label="Clear"]') || surface.querySelector('button[title="Clear"]');
        if (clear) clear.click();
    };
    const headerFormat = bytes => {
        const text=(offset,count)=>String.fromCharCode(...bytes.slice(offset,offset+count));
        if (text(0,4)==='fLaC') return 'flac';
        if (text(0,3)==='ID3' || (bytes[0]===255 && (bytes[1]&224)===224 && (bytes[1]&6)!==0)) return 'mp3';
        if (text(0,4)==='OggS') return 'ogg';
        if (text(4,4)==='ftyp') return 'm4a';
        if (text(0,4)==='RIFF' && text(8,4)==='WAVE') return 'wav';
        return null;
    };
    const decrypt = (file,name) => new Promise((resolve,reject) => {
        worker=new Worker(new URL('file=rvc_music/assets/offline.worker.js',document.baseURI));
        worker.onerror=()=>reject(new Error('解密模块未能启动，请刷新页面后重试。'));
        worker.onmessage=async event=>{
            const response=event.data;
            if (response.method==='ready') {
                worker.postMessage({type:'RPC',id:1,method:'CommonDecrypt',params:[{name,raw:file}]});
            } else if (response.id===1) {
                if (response.error) return reject(new Error('文件损坏，或这个加密版本暂不支持。'));
                const result=response.result;
                if (!result?.status || !result.file) return reject(new Error('这个加密版本暂不支持，未导入原文件。'));
                try {
                    const blob=await (await fetch(result.file)).blob();
                    const format=headerFormat(new Uint8Array(await blob.slice(0,16).arrayBuffer()));
                    if (!['mp3','flac','m4a','ogg'].includes(format)) throw new Error('解密结果不是可识别的音频，请检查文件版本。');
                    URL.revokeObjectURL(result.file);
                    resolve({blob,format});
                } catch(error) { reject(error); }
            }
        };
    });
    const send = async (file,decrypted) => {
        const token=root.querySelector('#music-import-token textarea') || root.querySelector('#music-import-token input');
        if (!token) throw new Error('上传入口未就绪，请刷新页面。');
        const setter=Object.getOwnPropertyDescriptor(token instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,'value').set;
        setter.call(token,ticket); token.dispatchEvent(new Event('input',{bubbles:true}));
        await Promise.resolve();
        const input=root.querySelector((decrypted?'#music-import-decoded':'#music-import-normal')+' input[type=file]');
        if (!input) throw new Error('上传入口未就绪，请刷新页面。');
        const transfer=new DataTransfer(); transfer.items.add(file); input.files=transfer.files;
        input.dispatchEvent(new Event('change',{bubbles:true}));
    };
    const importFile = async files => {
        if (busy) return;
        busy=true; surface.dataset.importBusy='true'; clearDownload();
        ticket=crypto.randomUUID();
        const current=ticket;
        timeout=setTimeout(()=>{
            if (busy && current===ticket) { resetPlayer(); finish(); message('导入超时，请重新选择文件。','error'); }
        },120000);
        try {
            resetPlayer();
            if (files.length!==1) throw new Error('单次推理请一次拖入一个文件。');
            const file=files[0];
            if (!file.size || file.size>512*1024*1024) throw new Error('文件为空或超过512MB。');
            message('正在识别：'+file.name);
            const bytes=new Uint8Array(await file.slice(0,16).arrayBuffer());
            const magic=String.fromCharCode(...bytes.slice(0,8))==='CTENFDAM';
            let ext=file.name.split('.').pop().toLowerCase();
            if (magic) ext='ncm';
            const plain=headerFormat(bytes);
            if (!magic && plain) {
                const name=ext!==plain ? file.name.replace(/\.[^.]+$/,'')+'.'+plain : file.name;
                message('正在导入音频…');
                await send(new File([file],name,{type:file.type || 'audio/'+plain}),false);
            } else if (supported.has(ext)) {
                message('检测到加密音乐，正在本地解密：'+file.name);
                const result=await decrypt(file,file.name.replace(/\.[^.]+$/,'')+'.'+ext);
                if (current!==ticket) return;
                const name=file.name.replace(/\.[^.]+$/,'')+'_已解密.'+result.format;
                message('解密完成，正在载入播放器…');
                await send(new File([result.blob],name,{type:result.blob.type}),true);
            } else if (unsupported.has(ext)) {
                throw new Error('暂不支持 .'+ext+' 的这个加密格式，请使用普通音频或受支持的 NCM／QMC 文件。');
            } else {
                message('正在导入音频…'); await send(file,false);
            }
        } catch(error) {
            if (current===ticket) { finish(); message('导入失败：'+error.message,'error'); }
        }
    };
    // Capture at the component boundary, before Svelte's Audio upload handler.
    surface.addEventListener('change',event=>{
        if (event.target.matches('input[type=file]')) {
            const files=Array.from(event.target.files || []);
            event.stopImmediatePropagation(); event.preventDefault();
            if (files.length) importFile(files);
        }
    },true);
    surface.addEventListener('drop',event=>{
        event.preventDefault(); event.stopImmediatePropagation();
        importFile(Array.from(event.dataTransfer?.files || []));
    },true);
    surface.addEventListener('dragover',event=>event.preventDefault(),true);
    surface.addEventListener('click',event=>{
        if (!busy && event.target.closest('button[aria-label="Clear"]')) {
            clearDownload(); message('可重新拖入音频或加密音乐。','idle');
        }
    },true);
    root.addEventListener('click',event=>{
        const button=event.target.closest('button');
        if (busy && button && ['转换','试处理30秒','恢复最近任务','更新效果／合成'].includes(button.textContent.trim())) {
            event.preventDefault(); event.stopImmediatePropagation();
        }
    },true);
    const patch = () => {
        surface.querySelectorAll('input[type=file]').forEach(input=>{input.accept='audio/*,'+[...supported,...unsupported].map(ext=>'.'+ext).join(',');});
        const node=status();
        if (busy && node?.dataset.ticket===ticket && ['ready','error'].includes(node.dataset.state)) {
            if (node.dataset.state==='ready') {
                const download=root.querySelector('#music-import-download');
                if (download) download.style.display='';
            }
            finish();
        }
    };
    const observer=new MutationObserver(patch);
    observer.observe(root,{childList:true,subtree:true}); patch();
    window.addEventListener('pagehide',()=>{finish();observer.disconnect();},{once:true});
    return [];
}
