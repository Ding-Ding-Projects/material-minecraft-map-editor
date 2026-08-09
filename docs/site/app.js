const tabs=[...document.querySelectorAll('.nav-tab')];
const pages=[...document.querySelectorAll('.page-section')];
function showTab(name){tabs.forEach(t=>t.classList.toggle('is-active',t.dataset.tab===name));pages.forEach(p=>{const active=p.dataset.page===name;p.hidden=!active;p.classList.toggle('is-visible',active)});history.replaceState(null,'',`#${name}`);document.querySelector(`#${name}`)?.focus({preventScroll:true})}
tabs.forEach(tab=>tab.addEventListener('click',()=>showTab(tab.dataset.tab)));
document.querySelectorAll('[data-tab-link]').forEach(link=>link.addEventListener('click',()=>showTab(link.dataset.tabLink)));
const initial=location.hash.slice(1);if(tabs.some(t=>t.dataset.tab===initial))showTab(initial);
const search=document.querySelector('#feature-search');const cards=[...document.querySelectorAll('.feature-card')];const empty=document.querySelector('#feature-empty');
search?.addEventListener('input',()=>{const query=search.value.trim().toLowerCase();let count=0;cards.forEach(card=>{const match=!query||card.dataset.search.includes(query)||card.textContent.toLowerCase().includes(query);card.hidden=!match;if(match)count++});empty.hidden=count!==0});
document.addEventListener('keydown',e=>{if(e.key==='/'&&document.activeElement!==search){e.preventDefault();showTab('features');search?.focus()}if(e.key==='Escape'&&document.activeElement===search){search.value='';search.dispatchEvent(new Event('input'));search.blur()}});
