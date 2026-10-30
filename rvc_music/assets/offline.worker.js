// Local-only adapter for the pinned Unlock Music worker.
self.fetch = async () => ({ok:false, status:503,
  json:async()=>({}), arrayBuffer:async()=>new ArrayBuffer(0)});
importScripts('patched.worker.js');
