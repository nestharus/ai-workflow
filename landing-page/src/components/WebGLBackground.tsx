import { useRef, useEffect } from "react";

const VERTEX_SHADER = `
attribute vec2 a_position;
void main() {
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = `
precision mediump float;
uniform float u_time;
uniform vec2 u_resolution;
uniform float u_scroll;

vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec2 mod289(vec2 x){return x-floor(x*(1.0/289.0))*289.0;}
vec3 permute(vec3 x){return mod289(((x*34.0)+1.0)*x);}
float snoise(vec2 v){
  const vec4 C=vec4(0.211324865405187,0.366025403784439,-0.577350269189626,0.024390243902439);
  vec2 i=floor(v+dot(v,C.yy));
  vec2 x0=v-i+dot(i,C.xx);
  vec2 i1;
  i1=(x0.x>x0.y)?vec2(1.0,0.0):vec2(0.0,1.0);
  vec4 x12=x0.xyxy+C.xxzz;
  x12.xy-=i1;
  i=mod289(i);
  vec3 p=permute(permute(i.y+vec3(0.0,i1.y,1.0))+i.x+vec3(0.0,i1.x,1.0));
  vec3 m=max(0.5-vec3(dot(x0,x0),dot(x12.xy,x12.xy),dot(x12.zw,x12.zw)),0.0);
  m=m*m;m=m*m;
  vec3 x=2.0*fract(p*C.www)-1.0;
  vec3 h=abs(x)-0.5;
  vec3 ox=floor(x+0.5);
  vec3 a0=x-ox;
  m*=1.79284291400159-0.85373472095314*(a0*a0+h*h);
  vec3 g;
  g.x=a0.x*x0.x+h.x*x0.y;
  g.yz=a0.yz*x12.xz+h.yz*x12.yw;
  return 130.0*dot(m,g);
}

void main(){
  vec2 uv=gl_FragCoord.xy/u_resolution;
  float aspect=u_resolution.x/u_resolution.y;
  vec2 p=vec2(uv.x*aspect,uv.y);

  float s=u_scroll;
  float freq1=mix(1.5,0.6,s);
  float freq2=mix(3.0,1.2,s);
  float sharpness=mix(0.8,0.3,s);

  float n1=snoise(p*freq1+u_time*0.035);
  float n2=snoise(p*freq2-u_time*0.05+50.0);
  float n3=snoise(p*0.7+vec2(u_time*0.02,-u_time*0.025));
  float n4=snoise(p*mix(4.0,1.5,s)+u_time*0.08+200.0);

  float lightPulse=0.85+0.15*sin(u_time*0.15);
  float lightWarm=0.5+0.5*sin(u_time*0.08+1.5);

  vec3 base=vec3(0.035,0.04,0.07);
  vec3 deep=mix(vec3(0.10,0.08,0.18),vec3(0.06,0.05,0.12),s);
  vec3 smoke=mix(vec3(0.14,0.13,0.20),vec3(0.08,0.07,0.14),s);
  vec3 ember=mix(vec3(0.20,0.12,0.06),vec3(0.12,0.06,0.04),s);
  vec3 cool=mix(vec3(0.06,0.10,0.22),vec3(0.04,0.06,0.15),s);

  vec3 color=base;
  color=mix(color,deep,smoothstep(-0.4,0.4,n1)*0.9);
  color=mix(color,smoke,smoothstep(-0.1*sharpness,0.5*sharpness,n2)*0.5);
  color+=ember*smoothstep(0.2,0.7,n3)*0.25*lightWarm;
  color+=cool*smoothstep(0.3,0.8,n4)*0.18*(1.0-lightWarm*0.3);

  vec2 lightPos=mix(vec2(0.7,0.9),vec2(0.5,0.5),s);
  float lightDist=length(uv-lightPos);
  float lightFalloff=1.0-smoothstep(0.0,1.2,lightDist)*0.25;
  color*=lightFalloff*lightPulse;

  float vx=abs(uv.x-0.5)*2.0;
  float vignette=1.0-vx*vx*0.3;
  color*=vignette;

  gl_FragColor=vec4(color,1.0);
}
`;

function createShader(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error("Shader compile error:", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function createProgram(gl: WebGLRenderingContext, vs: WebGLShader, fs: WebGLShader): WebGLProgram | null {
  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error("Program link error:", gl.getProgramInfoLog(program));
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

const SCALE = 0.2;

export function WebGLBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl", { alpha: false, antialias: false });
    if (!gl) return;

    const vs = createShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
    const fs = createShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    if (!vs || !fs) return;

    const program = createProgram(gl, vs, fs);
    if (!program) return;

    // Fullscreen quad
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );

    const aPosition = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(aPosition);
    gl.vertexAttribPointer(aPosition, 2, gl.FLOAT, false, 0, 0);

    const uTime = gl.getUniformLocation(program, "u_time");
    const uResolution = gl.getUniformLocation(program, "u_resolution");
    const uScroll = gl.getUniformLocation(program, "u_scroll");

    gl.useProgram(program);

    // Reduced motion check
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Sizing
    function resize() {
      if (!canvas) return;
      const docHeight = Math.max(
        document.body.scrollHeight,
        document.documentElement.scrollHeight,
      );
      const w = window.innerWidth;
      const h = docHeight;
      canvas.style.height = `${h}px`;
      canvas.width = Math.round(w * SCALE);
      canvas.height = Math.round(h * SCALE);
      gl!.viewport(0, 0, canvas.width, canvas.height);
    }

    resize();
    window.addEventListener("resize", resize);
    const resizeInterval = setInterval(resize, 2000);

    // Scroll tracking
    let scrollY = 0;
    function onScroll() {
      scrollY = window.scrollY;
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    // Animation loop
    let raf = 0;
    let lastFrame = 0;
    const startTime = performance.now();

    function render(now: number) {
      if (!prefersReducedMotion) {
        raf = requestAnimationFrame(render);
      }

      // Throttle to ~20fps
      if (now - lastFrame < 50 && !prefersReducedMotion) return;
      lastFrame = now;

      const time = (now - startTime) / 1000;
      const maxScroll = Math.max(
        1,
        document.documentElement.scrollHeight - window.innerHeight,
      );
      const scrollNorm = Math.min(1, Math.max(0, scrollY / maxScroll));

      gl!.uniform1f(uTime, time);
      gl!.uniform2f(uResolution, canvas!.width, canvas!.height);
      gl!.uniform1f(uScroll, scrollNorm);
      gl!.drawArrays(gl!.TRIANGLES, 0, 6);
    }

    if (prefersReducedMotion) {
      // Render a single static frame
      render(performance.now());
    } else {
      raf = requestAnimationFrame(render);
    }

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("scroll", onScroll);
      clearInterval(resizeInterval);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      gl.deleteBuffer(buffer);
    };
  }, []);

  return <canvas ref={canvasRef} className="bg-canvas" aria-hidden="true" />;
}
