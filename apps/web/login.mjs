import {createAuthClient} from './auth-client.mjs';
const client=createAuthClient();
const status=document.getElementById('status'),container=document.getElementById('googleButton'),account=document.getElementById('account'),retry=document.getElementById('retry');
let busy=false,expiry;
function failure(error){container.hidden=true;status.textContent=error.message||'Sign-in is unavailable. Please try again.';retry.hidden=false}
function signedIn(identity){window.location.replace('/collection');clearTimeout(expiry);container.hidden=true;account.hidden=false;document.getElementById('email').textContent=identity.email;status.textContent='You’re signed in to Pocket Analytics.';retry.hidden=true}
function googleLibrary(){return new Promise((resolve,reject)=>{
 if(window.google?.accounts?.id){resolve(window.google.accounts.id);return}
 const script=document.createElement('script');script.src='https://accounts.google.com/gsi/client';script.async=true;
 const timer=setTimeout(()=>reject(new Error('Google sign-in could not load. Please try again.')),10000);
 script.onload=()=>{clearTimeout(timer);window.google?.accounts?.id?resolve(window.google.accounts.id):reject(new Error('Google sign-in could not load. Please try again.'))};
 script.onerror=()=>{clearTimeout(timer);reject(new Error('Google sign-in could not load. Please try again.'))};document.head.appendChild(script);
})}
async function start(){
 try{
  const identity=await client.current();if(identity){signedIn(identity);return}
  const challenge=await client.challenge();const google=await googleLibrary();
  google.initialize({client_id:challenge.client_id,nonce:challenge.nonce,auto_select:false,callback:async response=>{
   if(busy)return;busy=true;clearTimeout(expiry);container.hidden=true;status.textContent='Signing you in…';
   try{signedIn(await client.signIn(response.credential,challenge))}catch(error){failure(error)}finally{busy=false}
  }});
  container.hidden=false;google.renderButton(container,{type:'standard',theme:'outline',size:'large',text:'signin_with',shape:'pill',width:Math.min(300,container.clientWidth)});
  status.textContent='Use the Google account chosen for this app.';
  expiry=setTimeout(()=>failure(new Error('This sign-in expired. Please try again.')),challenge.expires_in*1000);
 }catch(error){failure(error)}
}
retry.addEventListener('click',()=>window.location.reload());
document.getElementById('signOut').addEventListener('click',async event=>{
 event.currentTarget.disabled=true;
 try{await client.signOut();window.google?.accounts?.id?.disableAutoSelect();window.location.reload()}
 catch(error){status.textContent=error.message;event.currentTarget.disabled=false}
});
start();
