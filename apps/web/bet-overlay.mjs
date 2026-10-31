import {openBotBuilder,restoreBotDraft} from './bot-builder.mjs';
export function openBetOverlay(selections){if(selections?.length)openBotBuilder({selections})}

if(typeof document!=='undefined'){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>restoreBotDraft(),{once:true});else restoreBotDraft()}
