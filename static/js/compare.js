const left=document.getElementById('left'),right=document.getElementById('right'),sync=document.getElementById('sync');let updating=false;
function bind(source,target){source.addEventListener('camera-change',()=>{if(!sync.checked||updating)return;updating=true;const o=source.getCameraOrbit();target.cameraOrbit=o.theta+'rad '+o.phi+'rad auto';requestAnimationFrame(()=>updating=false);});}
bind(left,right);bind(right,left);
