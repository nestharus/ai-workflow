const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  // Collect console messages
  const logs = [];
  page.on('console', msg => logs.push(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => logs.push(`[PAGE ERROR] ${err.message}`));

  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);

  // Check if WebGL canvas exists and has content
  const canvasInfo = await page.evaluate(() => {
    const canvas = document.querySelector('.bg-canvas');
    if (!canvas) return { exists: false };
    const rect = canvas.getBoundingClientRect();
    const style = window.getComputedStyle(canvas);
    return {
      exists: true,
      tagName: canvas.tagName,
      width: canvas.width,
      height: canvas.height,
      styleWidth: style.width,
      styleHeight: style.height,
      stylePosition: style.position,
      styleZIndex: style.zIndex,
      display: style.display,
      visibility: style.visibility,
      opacity: style.opacity,
      rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
    };
  });

  // Check grain overlay
  const grainInfo = await page.evaluate(() => {
    const grain = document.querySelector('.grain-overlay');
    if (!grain) return { exists: false };
    return { exists: true, opacity: window.getComputedStyle(grain).opacity };
  });

  // Check all sections exist
  const sections = await page.evaluate(() => {
    const ids = ['hero','problems','pipeline','review','differentiator','features','pricing','faq','waitlist-final'];
    return ids.map(id => ({ id, exists: !!document.getElementById(id) }));
  });

  // Check root positioning
  const rootInfo = await page.evaluate(() => {
    const root = document.getElementById('root');
    const style = window.getComputedStyle(root);
    return { position: style.position, overflow: style.overflow, height: style.height };
  });

  console.log('=== Console Logs ===');
  logs.forEach(l => console.log(l));
  console.log('\n=== Canvas Info ===');
  console.log(JSON.stringify(canvasInfo, null, 2));
  console.log('\n=== Grain Info ===');
  console.log(JSON.stringify(grainInfo, null, 2));
  console.log('\n=== Root Info ===');
  console.log(JSON.stringify(rootInfo, null, 2));
  console.log('\n=== Sections ===');
  sections.forEach(s => console.log(`  ${s.id}: ${s.exists ? 'OK' : 'MISSING'}`));

  await browser.close();
})();
