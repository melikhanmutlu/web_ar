    document.addEventListener('DOMContentLoaded',()=>{
      const mobile=matchMedia('(max-width: 768px)').matches;
      const key='arvision-ar-onboarding-v1'; const overlay=document.getElementById('mobileArOnboarding');
      if(mobile&&!localStorage.getItem(key)) overlay.style.display='flex';
      document.getElementById('onboardingDismiss')?.addEventListener('click',()=>{localStorage.setItem(key,'dismissed');overlay.style.display='none';});
      document.getElementById('onboardingStartAr')?.addEventListener('click',()=>{localStorage.setItem(key,'started');overlay.style.display='none';document.getElementById('arButton')?.click();});
    });
