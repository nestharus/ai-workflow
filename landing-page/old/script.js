/* ================================================
   OULIPOLY AUTOMATON — LANDING PAGE SCRIPTS
   WebGL background + Layer Explorer + Particle System + UI
   ================================================ */

(function () {
  'use strict';

  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;


  /* ------------------------------------------------
     1. WEBGL BACKGROUND SHADER
     Flowing noise field in dark blues and teals.
     Mouse-reactive glow. Fixed behind all content.
     ------------------------------------------------ */

  var VERT_SRC = [
    'attribute vec2 a_position;',
    'void main() { gl_Position = vec4(a_position, 0.0, 1.0); }'
  ].join('\n');

  var FRAG_SRC = [
    'precision mediump float;',
    'uniform float u_time;',
    'uniform vec2 u_resolution;',
    'uniform float u_scroll;',       // 0..1 normalized scroll position
    '',
    'vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}',
    'vec2 mod289(vec2 x){return x-floor(x*(1.0/289.0))*289.0;}',
    'vec3 permute(vec3 x){return mod289(((x*34.0)+1.0)*x);}',
    '',
    'float snoise(vec2 v){',
    '  const vec4 C=vec4(0.211324865405187,0.366025403784439,-0.577350269189626,0.024390243902439);',
    '  vec2 i=floor(v+dot(v,C.yy));',
    '  vec2 x0=v-i+dot(i,C.xx);',
    '  vec2 i1;',
    '  i1=(x0.x>x0.y)?vec2(1.0,0.0):vec2(0.0,1.0);',
    '  vec4 x12=x0.xyxy+C.xxzz;',
    '  x12.xy-=i1;',
    '  i=mod289(i);',
    '  vec3 p=permute(permute(i.y+vec3(0.0,i1.y,1.0))+i.x+vec3(0.0,i1.x,1.0));',
    '  vec3 m=max(0.5-vec3(dot(x0,x0),dot(x12.xy,x12.xy),dot(x12.zw,x12.zw)),0.0);',
    '  m=m*m;m=m*m;',
    '  vec3 x=2.0*fract(p*C.www)-1.0;',
    '  vec3 h=abs(x)-0.5;',
    '  vec3 ox=floor(x+0.5);',
    '  vec3 a0=x-ox;',
    '  m*=1.79284291400159-0.85373472095314*(a0*a0+h*h);',
    '  vec3 g;',
    '  g.x=a0.x*x0.x+h.x*x0.y;',
    '  g.yz=a0.yz*x12.xz+h.yz*x12.yw;',
    '  return 130.0*dot(m,g);',
    '}',
    '',
    'void main(){',
    '  vec2 uv=gl_FragCoord.xy/u_resolution;',
    '  float aspect=u_resolution.x/u_resolution.y;',
    '  vec2 p=vec2(uv.x*aspect,uv.y);',
    '',
    // Scroll-dependent texture: vary noise frequency + octaves
    // Top (scroll=0): glass — sharp, high-freq, transparent-like
    // Mid (scroll~0.3): liquid — smooth, flowing, larger patterns
    // Mid (scroll~0.6): cloth — medium, woven, layered
    // Bot (scroll~1.0): velvet — very smooth, deep, soft shadows
    '  float s=u_scroll;',
    '  float freq1=mix(1.5,0.6,s);',     // glass→velvet: higher to lower freq
    '  float freq2=mix(3.0,1.2,s);',      // fine detail fades
    '  float sharpness=mix(0.8,0.3,s);',  // glass=sharp, velvet=soft
    '',
    '  float n1=snoise(p*freq1+u_time*0.035);',
    '  float n2=snoise(p*freq2-u_time*0.05+50.0);',
    '  float n3=snoise(p*0.7+vec2(u_time*0.02,-u_time*0.025));',
    '  float n4=snoise(p*mix(4.0,1.5,s)+u_time*0.08+200.0);',
    '',
    // Time-based lighting: slow brightness pulses
    '  float lightPulse=0.85+0.15*sin(u_time*0.15);',
    '  float lightWarm=0.5+0.5*sin(u_time*0.08+1.5);',
    '',
    // Base palette shifts with scroll
    '  vec3 base=vec3(0.035,0.04,0.07);',
    '  vec3 deep=mix(vec3(0.10,0.08,0.18),vec3(0.06,0.05,0.12),s);',
    '  vec3 smoke=mix(vec3(0.14,0.13,0.20),vec3(0.08,0.07,0.14),s);',
    '  vec3 ember=mix(vec3(0.20,0.12,0.06),vec3(0.12,0.06,0.04),s);',
    '  vec3 cool=mix(vec3(0.06,0.10,0.22),vec3(0.04,0.06,0.15),s);',
    '',
    '  vec3 color=base;',
    '  color=mix(color,deep,smoothstep(-0.4,0.4,n1)*0.9);',
    '  color=mix(color,smoke,smoothstep(-0.1*sharpness,0.5*sharpness,n2)*0.5);',
    '  color+=ember*smoothstep(0.2,0.7,n3)*0.25*lightWarm;',
    '  color+=cool*smoothstep(0.3,0.8,n4)*0.18*(1.0-lightWarm*0.3);',
    '',
    // Lighting: directional light that shifts with scroll
    // Top: light from above-right, bottom: light from center
    '  vec2 lightPos=mix(vec2(0.7,0.9),vec2(0.5,0.5),s);',
    '  float lightDist=length(uv-lightPos);',
    '  float lightFalloff=1.0-smoothstep(0.0,1.2,lightDist)*0.25;',
    '  color*=lightFalloff*lightPulse;',
    '',
    // Horizontal vignette (preserved)
    '  float vx=abs(uv.x-0.5)*2.0;',
    '  float vignette=1.0-vx*vx*0.3;',
    '  color*=vignette;',
    '',
    '  gl_FragColor=vec4(color,1.0);',
    '}'
  ].join('\n');

  function initWebGL() {
    var canvas = document.getElementById('bg-canvas');
    if (!canvas) return;

    var gl = canvas.getContext('webgl', { alpha: false, antialias: false });
    if (!gl) {
      canvas.style.display = 'none';
      document.body.style.backgroundColor = '#060a12';
      document.querySelector('.hero').style.backgroundColor = '#060a12';
      return;
    }

    function compileShader(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        canvas.style.display = 'none';
        return null;
      }
      return s;
    }

    var vs = compileShader(gl.VERTEX_SHADER, VERT_SRC);
    var fs = compileShader(gl.FRAGMENT_SHADER, FRAG_SRC);
    if (!vs || !fs) return;

    var program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      canvas.style.display = 'none';
      return;
    }
    gl.useProgram(program);

    var posAttr = gl.getAttribLocation(program, 'a_position');
    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
      -1, -1, 1, -1, -1, 1,
      -1, 1, 1, -1, 1, 1
    ]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(posAttr);
    gl.vertexAttribPointer(posAttr, 2, gl.FLOAT, false, 0, 0);

    var uTime = gl.getUniformLocation(program, 'u_time');
    var uRes = gl.getUniformLocation(program, 'u_resolution');
    var uScroll = gl.getUniformLocation(program, 'u_scroll');

    var scale = 0.2; // low res for performance — canvas covers full page
    var currentScroll = 0;

    var lastDocHeight = 0;

    function resize() {
      var w = window.innerWidth;
      var h = Math.max(document.documentElement.scrollHeight, window.innerHeight);
      // Skip resize if height hasn't changed significantly
      if (Math.abs(h - lastDocHeight) < 10 && canvas.style.width === w + 'px') return;
      lastDocHeight = h;
      canvas.width = Math.round(w * scale);
      canvas.height = Math.round(h * scale);
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    window.addEventListener('resize', resize, { passive: true });
    resize();

    // Recheck document height periodically (FAQ opens, content loads, etc.)
    setInterval(resize, 2000);

    // Track scroll for shader and lighting system
    window.addEventListener('scroll', function () {
      var maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      currentScroll = window.scrollY / maxScroll;
    }, { passive: true });

    var startTime = performance.now();
    var lastFrame = 0;

    function render(now) {
      if (now - lastFrame < 50) { // ~20fps for full-page canvas
        requestAnimationFrame(render);
        return;
      }
      lastFrame = now;

      var t = (now - startTime) * 0.001;

      gl.uniform1f(uTime, t);
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uScroll, currentScroll);

      gl.drawArrays(gl.TRIANGLES, 0, 6);
      requestAnimationFrame(render);
    }

    if (!reducedMotion) {
      requestAnimationFrame(render);
    } else {
      gl.uniform1f(uTime, 0);
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uScroll, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }
  }


  /* ------------------------------------------------
     2. LAYER PARTICLE SYSTEM (3D Stack in Hero)
     Particles rise from P0 to Main, with occasional
     demotions falling back down.
     ------------------------------------------------ */

  function initLayerParticles() {
    var canvas = document.getElementById('layer-particles');
    var stackEl = document.getElementById('layer-stack');
    if (!canvas || !stackEl || reducedMotion) return;

    var ctx = canvas.getContext('2d');
    if (!ctx) return;

    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var particles = [];
    var layerPositions = [];
    var W = 0, H = 0;

    function resize() {
      var rect = stackEl.getBoundingClientRect();
      W = rect.width;
      H = rect.height;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = W + 'px';
      canvas.style.height = H + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      updateLayerPositions();
    }

    function updateLayerPositions() {
      var panels = stackEl.querySelectorAll('.layer-panel');
      var stackRect = stackEl.getBoundingClientRect();
      layerPositions = [];
      panels.forEach(function (panel) {
        var r = panel.getBoundingClientRect();
        layerPositions.push({
          x: r.left - stackRect.left + r.width * 0.5,
          y: r.top - stackRect.top + r.height * 0.5,
          w: r.width,
          h: r.height
        });
      });
    }

    function spawnParticle() {
      if (layerPositions.length < 5) return null;
      var p0 = layerPositions[0];
      var isDemotion = Math.random() < 0.2;
      var startLayer = isDemotion ? (2 + Math.floor(Math.random() * 3)) : 0;
      var startPos = layerPositions[startLayer] || layerPositions[0];
      return {
        x: startPos.x + (Math.random() - 0.5) * startPos.w * 0.6,
        y: startPos.y,
        targetLayer: isDemotion ? 1 : 4,
        currentLayer: startLayer,
        isDemotion: isDemotion,
        speed: isDemotion ? 80 : 40,
        pauseTimer: 0,
        pauseDuration: 300 + Math.random() * 400,
        life: 1.0,
        size: 2 + Math.random() * 1.5,
        trail: [],
        done: false
      };
    }

    var lastSpawn = 0;
    var SPAWN_INTERVAL = 500;

    function tick(now) {
      ctx.clearRect(0, 0, W, H);

      if (now - lastSpawn > SPAWN_INTERVAL && particles.length < 20) {
        var np = spawnParticle();
        if (np) particles.push(np);
        lastSpawn = now;
      }

      for (var i = particles.length - 1; i >= 0; i--) {
        var p = particles[i];
        if (p.done) {
          p.life -= 0.02;
          if (p.life <= 0) {
            particles.splice(i, 1);
            continue;
          }
        }

        if (layerPositions.length < 5) continue;

        // Store trail
        p.trail.unshift({ x: p.x, y: p.y });
        if (p.trail.length > 3) p.trail.pop();

        if (!p.done) {
          // Determine target position
          var target = layerPositions[p.currentLayer];
          if (!target) continue;

          // Check if near target layer center
          var dy = Math.abs(p.y - target.y);
          if (dy < 3) {
            // At a layer
            if (p.pauseTimer < p.pauseDuration) {
              p.pauseTimer += 16;
            } else {
              // Move to next layer
              p.pauseTimer = 0;
              p.pauseDuration = 200 + Math.random() * 300;
              if (p.isDemotion) {
                if (p.currentLayer > p.targetLayer) {
                  p.currentLayer--;
                } else {
                  // Demotion reached target, now promote back up
                  p.isDemotion = false;
                  p.speed = 40;
                  p.targetLayer = 4;
                }
              } else {
                if (p.currentLayer < p.targetLayer) {
                  p.currentLayer++;
                } else {
                  p.done = true;
                }
              }
            }
          } else {
            // Move toward current layer
            var direction = target.y < p.y ? -1 : 1;
            var moveSpeed = p.isDemotion ? p.speed * 1.5 : p.speed;
            p.y += direction * moveSpeed * 0.016;
            // Add slight horizontal wobble
            p.x += (Math.random() - 0.5) * 0.5;
          }
        }

        // Draw trail
        for (var t = p.trail.length - 1; t >= 0; t--) {
          var trailAlpha = p.life * (1 - t / 3) * 0.3;
          var trailSize = p.size * (1 - t / 3) * 0.6;
          if (trailAlpha <= 0) continue;
          ctx.globalAlpha = trailAlpha;
          ctx.fillStyle = p.isDemotion ? '#f87171' : '#c0c8d0';
          ctx.beginPath();
          ctx.arc(p.trail[t].x, p.trail[t].y, trailSize, 0, Math.PI * 2);
          ctx.fill();
        }

        // Draw particle
        ctx.globalAlpha = p.life;
        var color = p.isDemotion ? '#f87171' : '#ffffff';
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();

        // Glow
        ctx.globalAlpha = p.life * 0.2;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * 3, 0, Math.PI * 2);
        var grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.size * 3);
        grad.addColorStop(0, p.isDemotion ? 'rgba(248,113,113,0.4)' : 'rgba(200,210,220,0.4)');
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = grad;
        ctx.fill();
      }

      ctx.globalAlpha = 1;
      requestAnimationFrame(tick);
    }

    window.addEventListener('resize', resize, { passive: true });

    // Wait for layout
    setTimeout(function () {
      resize();
      requestAnimationFrame(tick);
    }, 500);
  }


  /* ------------------------------------------------
     3. LAYER EXPLORER (replaces pipeline demo)
     ------------------------------------------------ */

  var LAYER_DESCRIPTIONS = {
    p0: 'The spec gets classified and routed into library buckets. Each bucket implements in parallel. When a slice hits a gap, planning researches and integrates a solution.',
    l1: 'Libraries implement in parallel. Each slice builds independently. When ambiguity is detected, the slice halts and planning researches a solution before resuming.',
    l2: 'Five architecture reviewers analyze the promoted code. Each reviewer evaluates a different dimension. The gate passes only when all reviewers approve.',
    l3: 'Quality review examines code complexity, diff impact, and test coverage. Lines that need refactoring are highlighted and improved. The quality gate enforces standards.',
    main: 'All branches converge into the main branch. Every gate has passed. Coverage is complete. The code is production-ready.'
  };

  // L1 positions (reused from original discover phase)
  var BLOB_POSITIONS = {
    discover: { x: 6, y: 38 }
  };

  var NODE_POSITIONS = {
    discover: [
      { x: 46, y: 14 }, { x: 70, y: 14 },
      { x: 46, y: 42 }, { x: 70, y: 42 },
      { x: 46, y: 70 }, { x: 70, y: 70 }
    ]
  };

  var layerExplorerTimeouts = [];

  function clearLayerTimeouts() {
    layerExplorerTimeouts.forEach(function (id) { clearTimeout(id); });
    layerExplorerTimeouts = [];
  }

  function layerTimeout(fn, delay) {
    var id = setTimeout(fn, delay);
    layerExplorerTimeouts.push(id);
    return id;
  }

  function initLayerExplorer() {
    var explorer = document.getElementById('layer-explorer');
    var viewport = document.getElementById('layer-viewport');
    var descEl = document.getElementById('layer-desc');
    if (!explorer || !viewport || !descEl) return;

    var tabs = explorer.querySelectorAll('.layer-tab');
    var views = viewport.querySelectorAll('.layer-view');
    var currentTab = null;
    var autoTimer = null;
    var isVisible = false;

    // L1 animation elements
    var l1View = viewport.querySelector('[data-view="l1"]');
    var blobNode = l1View ? l1View.querySelector('[data-node="blob"]') : null;
    var l1Nodes = l1View ? l1View.querySelectorAll('.demo-node:not([data-node="blob"])') : [];
    var routeLines = l1View ? l1View.querySelectorAll('.demo-route-line') : [];

    function setTab(tabName) {
      if (tabName === currentTab) return;
      currentTab = tabName;
      clearLayerTimeouts();

      tabs.forEach(function (tab) {
        tab.classList.toggle('is-active', tab.dataset.layerTab === tabName);
      });

      views.forEach(function (view) {
        var isTarget = view.dataset.view === tabName;
        view.classList.toggle('is-active', isTarget);
        // Reset animation classes
        view.classList.remove('is-animating', 'is-routing', 'is-highlighting', 'is-refactoring');
      });

      // Reset L1 nodes
      resetL1Nodes();

      // Start animation for active view
      var activeView = viewport.querySelector('.layer-view.is-active');
      if (activeView && !reducedMotion) {
        layerTimeout(function () {
          activeView.classList.add('is-animating');
          if (tabName === 'p0') animateP0(activeView);
          if (tabName === 'l1') animateL1();
          if (tabName === 'l2') animateL2(activeView);
          if (tabName === 'l3') animateL3(activeView);
          // main uses pure CSS animations, no JS needed
        }, 100);
      }

      descEl.style.opacity = '0';
      layerTimeout(function () {
        descEl.textContent = LAYER_DESCRIPTIONS[tabName] || '';
        descEl.style.opacity = '1';
      }, 250);
    }

    function resetL1Nodes() {
      if (!l1View) return;
      if (l1Nodes) {
        l1Nodes.forEach(function (node) {
          node.classList.remove('is-active', 'is-building', 'is-done', 'is-blocked', 'is-failed', 'is-visible');
          var bar = node.querySelector('.demo-node__bar');
          if (bar) {
            bar.style.transition = 'none';
            bar.style.width = '0%';
            bar.style.background = '';
          }
        });
      }
      if (blobNode) {
        blobNode.classList.remove('is-visible', 'is-classifying', 'is-done');
      }
      if (routeLines) {
        routeLines.forEach(function (line) {
          line.classList.remove('is-visible');
          line.style.width = '0';
        });
      }
    }

    function positionRouteLines() {
      if (!blobNode || !l1View) return;
      var vw = l1View.offsetWidth;
      var vh = l1View.offsetHeight;
      var blobPos = BLOB_POSITIONS.discover;
      var bx = (blobPos.x / 100) * vw + 70;
      var by = (blobPos.y / 100) * vh + 14;

      l1Nodes.forEach(function (node, i) {
        var line = routeLines[i];
        if (!line) return;
        var pos = NODE_POSITIONS.discover[i];
        var nx = (pos.x / 100) * vw;
        var ny = (pos.y / 100) * vh + 14;
        var dx = nx - bx;
        var dy = ny - by;
        var len = Math.sqrt(dx * dx + dy * dy);
        var angle = Math.atan2(dy, dx) * (180 / Math.PI);

        line.style.left = bx + 'px';
        line.style.top = by + 'px';
        line.style.transform = 'rotate(' + angle + 'deg)';
        line.dataset.length = len;
      });
    }

    // --- P0 Animation ---
    function animateP0(view) {
      layerTimeout(function () {
        view.classList.add('is-routing');
      }, 1200);
    }

    // --- L1 Animation (discover + build) ---
    function animateL1() {
      if (!l1View || !blobNode) return;

      var vw = l1View.offsetWidth;
      var vh = l1View.offsetHeight;
      var bp = BLOB_POSITIONS.discover;
      blobNode.style.left = bp.x + '%';
      blobNode.style.top = bp.y + '%';

      l1Nodes.forEach(function (node, i) {
        var pos = NODE_POSITIONS.discover[i];
        node.style.left = pos.x + '%';
        node.style.top = pos.y + '%';
      });

      blobNode.classList.add('is-visible');

      layerTimeout(function () {
        blobNode.classList.add('is-classifying');
      }, 500);

      layerTimeout(function () {
        positionRouteLines();
        routeLines.forEach(function (line, i) {
          layerTimeout(function () {
            var len = parseFloat(line.dataset.length) || 100;
            line.style.transition = 'width 350ms var(--ease-decel), opacity 200ms';
            line.style.width = len + 'px';
            line.classList.add('is-visible');
          }, i * 80);
        });
      }, 1000);

      l1Nodes.forEach(function (node, i) {
        layerTimeout(function () {
          node.classList.add('is-visible');
        }, 1400 + i * 100);
      });

      layerTimeout(function () {
        blobNode.classList.add('is-done');
        routeLines.forEach(function (line) {
          line.classList.remove('is-visible');
        });
      }, 2200);

      layerTimeout(function () {
        l1Nodes.forEach(function (node, i) {
          node.classList.add('is-building');
          var bar = node.querySelector('.demo-node__bar');
          if (bar) {
            bar.style.transition = 'width ' + (1.6 + i * 0.25) + 's linear';
            bar.style.width = '100%';
          }
        });
      }, 2400);

      layerTimeout(function () {
        l1Nodes[2].classList.remove('is-building');
        l1Nodes[2].classList.add('is-blocked');
        var bar = l1Nodes[2].querySelector('.demo-node__bar');
        if (bar) {
          bar.style.transition = 'none';
          bar.style.width = '40%';
          bar.style.background = 'var(--warning)';
        }
      }, 3400);

      layerTimeout(function () {
        l1Nodes[2].classList.remove('is-blocked');
        l1Nodes[2].classList.add('is-building');
        var bar = l1Nodes[2].querySelector('.demo-node__bar');
        if (bar) {
          bar.style.background = '';
          bar.style.transition = 'width 1.4s linear';
          bar.style.width = '100%';
        }
      }, 4400);

      var completeTimes = [3600, 4000, 5800, 4400, 4800, 5200];
      completeTimes.forEach(function (t, i) {
        layerTimeout(function () {
          if (!l1Nodes[i].classList.contains('is-blocked')) {
            l1Nodes[i].classList.remove('is-building');
            l1Nodes[i].classList.add('is-done');
          }
        }, t);
      });

      layerTimeout(function () {
        l1Nodes[2].classList.remove('is-building');
        l1Nodes[2].classList.add('is-done');
      }, 5800);
    }

    // --- L2 Animation ---
    function animateL2(view) {
      var reviewers = view.querySelectorAll('.l2-reviewer');
      var gate = view.querySelector('.l2-gate');

      // Reviewers light up one by one via CSS animation delays
      // Gate appears after reviewers
      layerTimeout(function () {
        if (gate) {
          gate.classList.add('is-visible');
        }
      }, 1700);

      layerTimeout(function () {
        if (gate) {
          gate.classList.add('is-filling');
        }
      }, 2000);

      layerTimeout(function () {
        if (gate) {
          gate.classList.add('is-pass');
        }
      }, 2800);
    }

    // --- L3 Animation ---
    function animateL3(view) {
      // Code lines appear via CSS animation
      // Highlighting after lines appear
      layerTimeout(function () {
        view.classList.add('is-highlighting');
      }, 1200);

      // Metrics fill
      layerTimeout(function () {
        var fills = view.querySelectorAll('.l3-metric__fill');
        if (fills[0]) fills[0].style.width = '35%';
        if (fills[1]) fills[1].style.width = '60%';
        if (fills[2]) fills[2].style.width = '90%';
      }, 1500);

      layerTimeout(function () {
        view.classList.add('is-refactoring');
      }, 2200);
    }

    // Tab click handler
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var name = this.dataset.layerTab;
        setTab(name);
        stopAutoPlay();
        setTimeout(startAutoPlay, 12000);
      });
    });

    var TAB_ORDER = ['p0', 'l1', 'l2', 'l3', 'main'];

    function startAutoPlay() {
      stopAutoPlay();
      autoTimer = setInterval(function () {
        var idx = TAB_ORDER.indexOf(currentTab);
        var next = TAB_ORDER[(idx + 1) % TAB_ORDER.length];
        setTab(next);
      }, 7000);
    }

    function stopAutoPlay() {
      if (autoTimer) {
        clearInterval(autoTimer);
        autoTimer = null;
      }
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !isVisible) {
          isVisible = true;
          setTab('p0');
          setTimeout(startAutoPlay, 4000);
        }
      });
    }, { threshold: 0.2 });

    observer.observe(viewport);

    window.addEventListener('resize', function () {
      if (currentTab === 'l1') positionRouteLines();
    }, { passive: true });
  }


  /* ------------------------------------------------
     4. SCROLL-TRIGGERED ANIMATIONS (IntersectionObserver)
     ------------------------------------------------ */
  function initScrollAnimations() {
    var elements = document.querySelectorAll('[data-animate]');
    if (!elements.length) return;

    if (reducedMotion) {
      elements.forEach(function (el) { el.classList.add('is-visible'); });
      return;
    }

    var groups = new Map();
    elements.forEach(function (el) {
      var parent = el.parentElement;
      if (!groups.has(parent)) groups.set(parent, []);
      groups.get(parent).push(el);
    });

    groups.forEach(function (children) {
      children.forEach(function (child, i) {
        if (children.length > 1 && i < 6) {
          child.style.transitionDelay = (i * 80) + 'ms';
        }
      });
    });

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

    elements.forEach(function (el) { observer.observe(el); });
  }


  /* ------------------------------------------------
     5. BENTO CARD MINI-DEMO TRIGGERS
     ------------------------------------------------ */
  function initBentoDemos() {
    if (reducedMotion) return;

    var demos = document.querySelectorAll('.bento-demo');

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var demo = entry.target;
          demo.classList.add('is-animating');

          // Routing: trigger editing phase after lines appear
          if (demo.classList.contains('bento-demo--routing')) {
            setTimeout(function () {
              demo.classList.add('is-editing');
            }, 1200);
          }

          // Coverage: fill cells one by one
          if (demo.classList.contains('bento-demo--coverage')) {
            var cells = demo.querySelectorAll('.coverage-cell');
            var counter = demo.querySelector('.coverage-counter');
            cells.forEach(function (cell, i) {
              setTimeout(function () {
                cell.classList.add('is-checked');
                if (counter) counter.textContent = (i + 1) + '/12';
                if (i === cells.length - 1 && counter) {
                  counter.classList.add('is-done');
                }
              }, 300 + i * 200);
            });
          }

          // Clarity: show underspec → options appear → one selected → constraint set
          if (demo.classList.contains('bento-demo--clarity')) {
            var underspec = demo.querySelector('.cf-underspec');
            var options = demo.querySelectorAll('.cf-option');
            var constraint = demo.querySelector('.cf-constraint');

            // Step 1: Underspec appears
            if (underspec) {
              setTimeout(function () {
                underspec.style.opacity = '1';
                underspec.style.transition = 'opacity 400ms';
              }, 300);
            }

            // Step 2: Options appear one by one
            options.forEach(function (opt, i) {
              setTimeout(function () {
                opt.style.opacity = '1';
                opt.style.transition = 'opacity 350ms';
              }, 800 + i * 250);
            });

            // Step 3: Second option gets selected
            setTimeout(function () {
              if (options[1]) options[1].classList.add('is-selected');
            }, 2200);

            // Step 4: Constraint confirmed
            setTimeout(function () {
              if (constraint) {
                constraint.style.opacity = '1';
                constraint.style.transition = 'opacity 400ms';
              }
            }, 2800);
          }

          // Self-healing: activate each step sequentially with glow
          if (demo.classList.contains('bento-demo--healing')) {
            var steps = demo.querySelectorAll('.hf-step');
            var stepDelays = [200, 800, 1600, 2400];
            steps.forEach(function (step, i) {
              setTimeout(function () {
                step.classList.add('is-active');
              }, stepDelays[i] + 300);
            });
          }

          observer.unobserve(demo);
        }
      });
    }, { threshold: 0.3 });

    demos.forEach(function (demo) { observer.observe(demo); });
  }

  function animateCounter(el, from, to, duration) {
    var start = performance.now();
    function step(now) {
      var progress = Math.min((now - start) / duration, 1);
      var value = Math.round(from + (to - from) * progress);
      el.textContent = value + '%';
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }


  /* ------------------------------------------------
     6. REVIEW CARD DEMO TRIGGERS
     ------------------------------------------------ */
  function initReviewDemos() {
    if (reducedMotion) return;

    var demos = document.querySelectorAll('.review-demo');

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-animating');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.3 });

    demos.forEach(function (demo) { observer.observe(demo); });
  }


  /* ------------------------------------------------
     7. NAVBAR SCROLL BEHAVIOR
     ------------------------------------------------ */
  function initNavScroll() {
    var nav = document.getElementById('nav');
    if (!nav) return;

    var ticking = false;

    function update() {
      if (window.scrollY > 50) {
        nav.classList.add('is-scrolled');
      } else {
        nav.classList.remove('is-scrolled');
      }
      ticking = false;
    }

    window.addEventListener('scroll', function () {
      if (!ticking) {
        requestAnimationFrame(update);
        ticking = true;
      }
    }, { passive: true });

    update();
  }


  /* ------------------------------------------------
     8. SCROLL INDICATOR FADE
     ------------------------------------------------ */
  function initScrollIndicator() {
    var cue = document.getElementById('scroll-cue');
    if (!cue) return;

    var hidden = false;

    window.addEventListener('scroll', function () {
      if (!hidden && window.scrollY > 100) {
        cue.classList.add('is-hidden');
        hidden = true;
      }
    }, { passive: true });
  }


  /* ------------------------------------------------
     9. SMOOTH SCROLL FOR ANCHOR LINKS
     ------------------------------------------------ */
  function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function (link) {
      link.addEventListener('click', function (e) {
        var id = this.getAttribute('href');
        if (id === '#') return;

        var target = document.querySelector(id);
        if (!target) return;

        e.preventDefault();

        var navH = document.getElementById('nav');
        var offset = navH ? navH.offsetHeight : 0;
        var pos = target.getBoundingClientRect().top + window.scrollY - offset - 20;

        window.scrollTo({ top: pos, behavior: 'smooth' });
      });
    });
  }


  /* ------------------------------------------------
     10. WAITLIST FORM
     ------------------------------------------------ */
  function initWaitlistForm() {
    var form = document.getElementById('waitlist-form');
    var emailInput = document.getElementById('waitlist-email');
    var statusEl = document.getElementById('waitlist-status');

    if (!form || !emailInput || !statusEl) return;

    function setStatus(html, type) {
      statusEl.innerHTML = html;
      statusEl.className = 'waitlist-form__status';
      if (type) statusEl.classList.add('waitlist-form__status--' + type);
    }

    function isValidEmail(email) {
      return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();

      var email = emailInput.value.trim();

      if (!email) {
        setStatus('Please enter your email address.', 'error');
        emailInput.focus();
        return;
      }

      if (!isValidEmail(email)) {
        setStatus('Please enter a valid email address.', 'error');
        emailInput.focus();
        return;
      }

      var btn = form.querySelector('.waitlist-form__btn');
      emailInput.disabled = true;
      btn.disabled = true;
      setStatus('Joining the waitlist...', 'loading');

      fetch('/api/waitlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email })
      })
        .then(function (res) {
          if (!res.ok) throw new Error('Server returned ' + res.status);
          return res.json();
        })
        .then(function () {
          setStatus('&#10003; You\'re on the list!', 'success');
          emailInput.value = '';
          emailInput.disabled = false;
          btn.disabled = false;
        })
        .catch(function () {
          setStatus('Something went wrong. Please try again.', 'error');
          emailInput.disabled = false;
          btn.disabled = false;
        });
    });
  }


  /* ------------------------------------------------
     11. FAQ ACCORDION (single-open)
     ------------------------------------------------ */
  function initFAQ() {
    var items = document.querySelectorAll('.faq-item');

    items.forEach(function (item) {
      item.addEventListener('toggle', function () {
        if (this.open) {
          items.forEach(function (other) {
            if (other !== item && other.open) other.open = false;
          });
        }
      });
    });
  }


  /* ------------------------------------------------
     12. ACCURACY COMPARISON BARS (horizontal)
     ------------------------------------------------ */
  function initAccuracyBars() {
    var container = document.getElementById('accuracy-comparison');
    if (!container) return;

    var fills = container.querySelectorAll('.accuracy-row__fill');
    var triggered = false;

    if (reducedMotion) {
      fills.forEach(function (fill) { fill.classList.add('is-filling'); });
      return;
    }

    var motionAnimate = (typeof Motion !== 'undefined' && Motion.animate) ? Motion.animate : null;

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !triggered) {
          triggered = true;

          if (motionAnimate) {
            fills.forEach(function (fill, i) {
              var targetWidth = fill.dataset.fill + '%';
              motionAnimate(fill, { width: ['0%', targetWidth] }, {
                duration: 1.8,
                delay: i * 0.15,
                ease: [0.22, 1, 0.36, 1]
              });
            });

            // Animate counter values
            var rows = container.querySelectorAll('.accuracy-row');
            rows.forEach(function (row, i) {
              var valueEl = row.querySelector('.accuracy-row__value');
              var fill = row.querySelector('.accuracy-row__fill');
              if (!valueEl || !fill) return;
              var target = parseInt(fill.dataset.fill, 10);
              motionAnimate(function (progress) {
                valueEl.textContent = Math.round(progress * target) + '%';
              }, { duration: 1.8, delay: i * 0.15, ease: [0.22, 1, 0.36, 1] });
            });
          } else {
            fills.forEach(function (fill) { fill.classList.add('is-filling'); });
          }

          observer.disconnect();
        }
      });
    }, { threshold: 0.3 });

    observer.observe(container);
  }


  /* ------------------------------------------------
     13. DIRECTIONAL LIGHTING SYSTEM
     Virtual point light that moves with scroll.
     Updates CSS custom properties on lit elements.
     ------------------------------------------------ */
  function initLighting() {
    if (reducedMotion) return;

    // Light starts top-right, moves to center as user scrolls
    var lightX = 0.8;   // 0=left, 1=right
    var lightY = -0.1;  // above viewport
    var lightIntensity = 0.6;
    var targetLX = lightX;
    var targetLY = lightY;
    var targetIntensity = lightIntensity;

    function updateLightFromScroll() {
      var maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      var s = window.scrollY / maxScroll; // 0..1

      // Light moves: top-right → center as we scroll
      targetLX = 0.8 - s * 0.4;     // 0.8 → 0.4
      targetLY = -0.1 + s * 0.7;    // -0.1 → 0.6
      // Intensity increases: dim → fully lit
      targetIntensity = 0.6 + s * 0.4; // 0.6 → 1.0
    }

    window.addEventListener('scroll', updateLightFromScroll, { passive: true });
    updateLightFromScroll();

    // Gather all lit elements
    var litSelectors = '.btn-primary, .btn-secondary, .glass-panel, .layer-panel__surface, .pricing-card, .layer-tab';
    var litElements = [];
    var elemCache = [];

    function gatherElements() {
      litElements = document.querySelectorAll(litSelectors);
      elemCache = [];
      litElements.forEach(function (el) {
        elemCache.push({
          el: el,
          rect: null
        });
      });
    }

    gatherElements();

    // Debounced regather on resize
    var resizeTimer;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(gatherElements, 300);
    }, { passive: true });

    var ticking = false;

    function applyLighting() {
      // Smooth lerp toward target
      lightX += (targetLX - lightX) * 0.08;
      lightY += (targetLY - lightY) * 0.08;
      lightIntensity += (targetIntensity - lightIntensity) * 0.08;

      var vpW = window.innerWidth;
      var vpH = window.innerHeight;

      // Light position in viewport coordinates
      var lpx = lightX * vpW;
      var lpy = lightY * vpH;

      for (var i = 0; i < elemCache.length; i++) {
        var el = elemCache[i].el;

        // Only update elements in/near viewport
        var rect = el.getBoundingClientRect();
        if (rect.bottom < -200 || rect.top > vpH + 200) continue;

        // Element center in viewport coords
        var cx = rect.left + rect.width * 0.5;
        var cy = rect.top + rect.height * 0.5;

        // Direction from element to light
        var dx = lpx - cx;
        var dy = lpy - cy;
        var dist = Math.sqrt(dx * dx + dy * dy);
        var norm = dist > 1 ? 1 / dist : 1;

        // Shadow: cast opposite to light direction
        var maxShift = 12;
        var sx = (-dx * norm * maxShift * lightIntensity);
        var sy = (-dy * norm * maxShift * lightIntensity);

        // Proximity glow: elements closer to light get brighter
        var maxDist = Math.sqrt(vpW * vpW + vpH * vpH) * 0.6;
        var proximity = Math.max(0, 1 - dist / maxDist);
        var li = lightIntensity;

        // White glow strength (the "stage light" hitting the element)
        var glowStr = (0.05 + proximity * li * 0.25);
        // Broader ambient glow
        var ambStr = (0.02 + proximity * li * 0.12);
        // Edge highlight on light-facing side
        var edgeStr = (0.04 + proximity * li * 0.16);
        // Dark shadow behind
        var darkStr = 0.4 - li * 0.1;

        // Inset highlight: on the side facing the light
        var insetY = dy > 0 ? 1 : -1;
        var insetX = dx > 0 ? 1 : -1;

        var shadow =
          // Tight edge glow
          '0 0 1px rgba(255,255,255,' + (0.1 + edgeStr).toFixed(3) + '),' +
          // Directional light glow (key shadow)
          sx.toFixed(1) + 'px ' + sy.toFixed(1) + 'px ' + (16 + li * 12).toFixed(0) + 'px rgba(255,255,255,' + glowStr.toFixed(3) + '),' +
          // Broader ambient wash
          (sx * 0.3).toFixed(1) + 'px ' + (sy * 0.3).toFixed(1) + 'px ' + (32 + li * 16).toFixed(0) + 'px rgba(255,255,255,' + ambStr.toFixed(3) + '),' +
          // Dark cast shadow (opposite side)
          (sx * 0.5).toFixed(1) + 'px ' + (sy * 0.5 + 4).toFixed(1) + 'px ' + (20 + li * 12).toFixed(0) + 'px rgba(0,0,0,' + darkStr.toFixed(3) + '),' +
          // Inset edge highlight
          'inset ' + insetX + 'px ' + insetY + 'px 0 rgba(255,255,255,' + (edgeStr + 0.05).toFixed(3) + ')';

        el.style.boxShadow = shadow;
      }

      requestAnimationFrame(applyLighting);
    }

    requestAnimationFrame(applyLighting);
  }


  /* ------------------------------------------------
     14. INIT
     ------------------------------------------------ */
  function init() {
    initWebGL();
    initNavScroll();
    initScrollIndicator();
    initSmoothScroll();
    initScrollAnimations();
    initLayerParticles();
    initLayerExplorer();
    initBentoDemos();
    initReviewDemos();
    initWaitlistForm();
    initFAQ();
    initAccuracyBars();
    initLighting();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
