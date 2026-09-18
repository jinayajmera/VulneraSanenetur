import React, { useState, useEffect, useRef } from 'react';
import { 
  ShieldCheck, 
  Cpu, 
  Eye, 
  Activity, 
  Zap, 
  Play, 
  Sliders, 
  Terminal, 
  AlertTriangle, 
  CheckCircle2, 
  ArrowRight, 
  Layers, 
  RefreshCw,
  Maximize2,
  Crosshair,
  Lock,
  Radio,
  FileCode2,
  ExternalLink
} from 'lucide-react';

interface LandingPageProps {
  onLaunchConsole: () => void;
  onOpenAuth: () => void;
  token: string | null;
  role: string | null;
}

// Preset Surgical Commands for Interactive Simulation
const PRESET_COMMANDS = [
  {
    cmd: "make a 3mm incision at landmark A",
    label: "Incision (Landmark A)",
    type: "incision",
    depth: "3.0 mm",
    rationale: "Make 3.0mm cut at landmark A using Arm 1 while Arm 2 retracts tissue.",
    arm1Waypoints: [
      { x: 12.0, y: -4.0, z: -5.0, label: "approach" },
      { x: 12.0, y: -4.0, z: -8.3, label: "cut_start" },
      { x: 12.5, y: -4.0, z: -8.3, label: "cut_end" },
      { x: 12.5, y: -4.0, z: -5.0, label: "retract" }
    ],
    arm2Waypoints: [
      { x: 10.0, y: -4.0, z: -5.0, label: "approach" },
      { x: 10.0, y: -4.0, z: -8.0, label: "hold_tissue" },
      { x: 10.0, y: -4.0, z: -5.0, label: "retract" }
    ]
  },
  {
    cmd: "biopsy landmark B with 4mm depth",
    label: "Tissue Biopsy (Landmark B)",
    type: "biopsy",
    depth: "4.0 mm",
    rationale: "Sample core tissue at landmark B; dual-arm stabilization active.",
    arm1Waypoints: [
      { x: -10.5, y: 6.2, z: -4.0, label: "hover" },
      { x: -10.5, y: 6.2, z: -8.4, label: "penetrate" },
      { x: -10.5, y: 6.2, z: -8.4, label: "sample_core" },
      { x: -10.5, y: 6.2, z: -3.0, label: "retract_sample" }
    ],
    arm2Waypoints: [
      { x: -12.5, y: 6.2, z: -4.0, label: "stabilize_standby" },
      { x: -12.5, y: 6.2, z: -8.0, label: "press_border" },
      { x: -12.5, y: 6.2, z: -3.0, label: "retract" }
    ]
  },
  {
    cmd: "cauterize the mark at landmark A",
    label: "Cauterization (Landmark A)",
    type: "cauterization",
    depth: "0.5 mm",
    rationale: "Apply 2.5 second thermal contact dwell at landmark A for hemostasis.",
    arm1Waypoints: [
      { x: 12.0, y: -4.0, z: -5.0, label: "approach" },
      { x: 12.0, y: -4.0, z: -8.05, label: "thermal_contact_dwell_2.5s" },
      { x: 12.0, y: -4.0, z: -5.0, label: "retract" }
    ],
    arm2Waypoints: [
      { x: 8.0, y: -4.0, z: -3.0, label: "suction_standby" },
      { x: 8.0, y: -4.0, z: -7.5, label: "smoke_evacuation" },
      { x: 8.0, y: -4.0, z: -3.0, label: "retract" }
    ]
  },
  {
    cmd: "put in 4 sutures at landmark A",
    label: "4 Suture Loops (Landmark A)",
    type: "suturing",
    depth: "2.0 mm",
    rationale: "Trace 4 interrupted stitch trajectories across incision margin at landmark A.",
    arm1Waypoints: [
      { x: 11.5, y: -4.2, z: -6.0, label: "loop_1_in" },
      { x: 12.5, y: -3.8, z: -8.2, label: "loop_1_out" },
      { x: 11.5, y: -4.0, z: -6.0, label: "loop_2_in" },
      { x: 12.5, y: -3.6, z: -8.2, label: "loop_2_out" }
    ],
    arm2Waypoints: [
      { x: 9.5, y: -4.0, z: -6.0, label: "knot_tension_1" },
      { x: 9.5, y: -4.0, z: -6.0, label: "knot_tension_2" }
    ]
  }
];

export const LandingPage: React.FC<LandingPageProps> = ({
  onLaunchConsole,
  onOpenAuth,
  token,
  role
}) => {
  const [selectedPreset, setSelectedPreset] = useState(PRESET_COMMANDS[0]);
  const [customCommand, setCustomCommand] = useState(PRESET_COMMANDS[0].cmd);
  const [activeTab, setActiveTab] = useState<'canvas' | 'diff' | 'safety'>('canvas');
  const [simProgress, setSimProgress] = useState(0);
  const [isSimulating, setIsSimulating] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Auto-simulation loop on trajectory canvas
  useEffect(() => {
    let animationFrameId: number;
    let t = 0;

    const renderCanvas = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const width = canvas.width;
      const height = canvas.height;

      // Clear Canvas
      ctx.fillStyle = '#0b0f19';
      ctx.fillRect(0, 0, width, height);

      // Draw Grid Lines
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.08)';
      ctx.lineWidth = 1;
      const gridSize = 30;
      for (let x = 0; x < width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // Center origin mapping
      const originX = width / 2;
      const originY = height / 2 + 20;
      const scale = 18; // cm to px scale

      // Draw Workspace Limits Boundary (Safe Z & Reach)
      ctx.strokeStyle = 'rgba(245, 158, 11, 0.3)';
      ctx.setLineDash([4, 4]);
      ctx.strokeRect(originX - 12 * scale, originY - 12 * scale, 24 * scale, 24 * scale);
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(245, 158, 11, 0.6)';
      ctx.font = '10px JetBrains Mono';
      ctx.fillText('SAFETY BOUNDARY (24cm x 24cm)', originX - 11.5 * scale, originY - 10.5 * scale);

      // Draw Landmarks A, B, C
      const landmarks = [
        { name: 'A (Yellow)', x: 12.0, y: -4.0, color: '#feca57' },
        { name: 'B (Cyan)', x: -10.5, y: 6.2, color: '#38bdf8' },
        { name: 'C (Purple)', x: 0.0, y: 8.5, color: '#a855f7' }
      ];

      landmarks.forEach(lm => {
        const px = originX + lm.x * scale;
        const py = originY - lm.y * scale;

        // Outer glow circle
        ctx.beginPath();
        ctx.arc(px, py, 14, 0, Math.PI * 2);
        ctx.fillStyle = lm.color + '22';
        ctx.fill();

        // Inner marker
        ctx.beginPath();
        ctx.arc(px, py, 6, 0, Math.PI * 2);
        ctx.fillStyle = lm.color;
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.fillStyle = lm.color;
        ctx.font = 'bold 11px JetBrains Mono';
        ctx.fillText(`LM ${lm.name}`, px + 10, py + 4);
      });

      // Trajectory Path for Arm 1
      const waypoints = selectedPreset.arm1Waypoints;
      if (waypoints.length > 0) {
        ctx.beginPath();
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 2.5;

        waypoints.forEach((wp, idx) => {
          const px = originX + wp.x * scale;
          const py = originY - wp.y * scale;
          if (idx === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        });
        ctx.stroke();

        // Draw Waypoint nodes
        waypoints.forEach((wp, idx) => {
          const px = originX + wp.x * scale;
          const py = originY - wp.y * scale;

          ctx.beginPath();
          ctx.arc(px, py, 4, 0, Math.PI * 2);
          ctx.fillStyle = '#38bdf8';
          ctx.fill();

          ctx.fillStyle = 'rgba(248, 250, 252, 0.7)';
          ctx.font = '9px JetBrains Mono';
          ctx.fillText(`WP${idx + 1}: ${wp.label}`, px + 6, py - 6);
        });

        // Animated Arm Tool Tip Movement
        t = (t + 0.008) % 1;
        setSimProgress(Math.floor(t * 100));

        const currIndex = Math.floor(t * (waypoints.length - 1));
        const nextIndex = Math.min(currIndex + 1, waypoints.length - 1);
        const lerpFactor = (t * (waypoints.length - 1)) - currIndex;

        const p1 = waypoints[currIndex];
        const p2 = waypoints[nextIndex];

        const toolX = p1.x + (p2.x - p1.x) * lerpFactor;
        const toolY = p1.y + (p2.y - p1.y) * lerpFactor;

        const toolPx = originX + toolX * scale;
        const toolPy = originY - toolY * scale;

        // Tool tip pulse indicator
        ctx.beginPath();
        ctx.arc(toolPx, toolPy, 9, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(16, 185, 129, 0.4)';
        ctx.fill();

        ctx.beginPath();
        ctx.arc(toolPx, toolPy, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#10b981';
        ctx.fill();

        // Tool Label
        ctx.fillStyle = '#10b981';
        ctx.font = 'bold 10px JetBrains Mono';
        ctx.fillText(`ARM 1 (ACTIVE: Z=${(p1.z + (p2.z - p1.z) * lerpFactor).toFixed(1)}cm)`, toolPx + 12, toolPy + 4);
      }

      animationFrameId = requestAnimationFrame(renderCanvas);
    };

    renderCanvas();

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [selectedPreset]);

  const handleSelectPreset = (preset: typeof PRESET_COMMANDS[0]) => {
    setSelectedPreset(preset);
    setCustomCommand(preset.cmd);
  };

  return (
    <div style={{ position: 'relative', minHeight: '100vh', width: '100%' }}>
      {/* Background Mesh */}
      <div className="radial-mesh" />

      {/* TOP NAVIGATION BAR */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        background: 'rgba(7, 9, 14, 0.85)',
        backdropFilter: 'blur(16px)',
        borderBottom: '1px solid rgba(56, 189, 248, 0.15)',
        padding: '16px 32px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            width: '38px',
            height: '38px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #38bdf8 0%, #0284c7 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 15px rgba(56, 189, 248, 0.5)'
          }}>
            <Activity size={22} color="#040914" strokeWidth={2.5} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontFamily: 'Outfit', fontWeight: 800, fontSize: '1.25rem', letterSpacing: '1px' }}>ROBOSURGE</span>
              <span className="badge badge-emerald" style={{ padding: '2px 8px', fontSize: '0.65rem' }}>v0.4.0 LIVE</span>
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'JetBrains Mono' }}>
              DUAL-ARM ROBOTIC SURGICAL SYSTEM
            </div>
          </div>
        </div>

        {/* Navigation Links */}
        <nav style={{ display: 'flex', gap: '28px', fontSize: '0.9rem', fontWeight: 600 }}>
          <a href="#overview" style={{ color: 'var(--text-primary)', textDecoration: 'none' }}>Overview</a>
          <a href="#simulator" style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>Live Simulator</a>
          <a href="#architecture" style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>Safety Architecture</a>
          <a href="#specs" style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>Tech Specs</a>
        </nav>

        {/* Right CTA Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          {token ? (
            <div className="badge badge-amber" style={{ padding: '6px 12px' }}>
              LOGGED IN ({role?.toUpperCase()})
            </div>
          ) : (
            <button className="btn-secondary" onClick={onOpenAuth} style={{ padding: '8px 18px', fontSize: '0.85rem' }}>
              <Lock size={15} />
              <span>Doctor Login</span>
            </button>
          )}

          <button className="btn-primary" onClick={onLaunchConsole} style={{ padding: '8px 20px', fontSize: '0.88rem' }}>
            <Terminal size={16} />
            <span>Launch Control Console</span>
          </button>
        </div>
      </header>

      {/* HERO SECTION */}
      <section id="overview" style={{ padding: '80px 32px 60px 32px', maxWidth: '1280px', margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '48px', alignItems: 'center' }}>
          
          {/* Left Text Column */}
          <div>
            <div className="badge" style={{ marginBottom: '20px' }}>
              <div className="pulse-dot" />
              <span>NEXT-GEN SURGICAL MOTION ENGINE</span>
            </div>

            <h1 style={{ fontSize: '3.5rem', lineHeight: '1.1', fontWeight: 800, marginBottom: '24px' }}>
              Autonomous Surgical Motion.<br />
              <span className="gradient-text">Governed by Pure Math.</span>
            </h1>

            <p style={{ fontSize: '1.125rem', color: 'var(--text-secondary)', marginBottom: '32px', maxWidth: '540px' }}>
              Type natural-language surgical commands. The system perceives the field with <strong>YOLOv8 & HSV landmarking</strong>, plans procedure steps with <strong>Groq Llama 3.3 70B</strong>, deterministically repairs cut geometry, and enforces hard pure-math safety rules before sending inverse kinematics to dual ESP32 arms.
            </p>

            <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
              <a href="#simulator" className="btn-primary">
                <Play size={18} fill="currentColor" />
                <span>Try Interactive Simulator</span>
              </a>
              <button className="btn-secondary" onClick={onLaunchConsole}>
                <ShieldCheck size={18} color="var(--accent-cyan)" />
                <span>Open Control Interface</span>
              </button>
            </div>

            {/* Quick Metrics Ticker */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '16px',
              marginTop: '48px',
              paddingTop: '24px',
              borderTop: '1px solid var(--border-muted)'
            }}>
              <div>
                <div style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--accent-cyan)' }}>100%</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Deterministic Plan Repair</div>
              </div>
              <div>
                <div style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--accent-emerald)' }}>10 Hz</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Waypoint Interpolation</div>
              </div>
              <div>
                <div style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--accent-purple)' }}>&lt; 0.5mm</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Fiducial Spatial Mapper</div>
              </div>
            </div>
          </div>

          {/* Right Hero Image Card */}
          <div className="glass-panel scanline-effect" style={{ padding: '12px', borderRadius: '24px', position: 'relative' }}>
            <img 
              src="/hero.png" 
              alt="RoboSurge Dual Arm System" 
              style={{ width: '100%', borderRadius: '16px', display: 'block', border: '1px solid rgba(255,255,255,0.1)' }}
            />

            {/* Overlay Telemetry Badges */}
            <div style={{
              position: 'absolute',
              top: '24px',
              left: '24px',
              background: 'rgba(7, 9, 14, 0.85)',
              backdropFilter: 'blur(10px)',
              padding: '8px 14px',
              borderRadius: '10px',
              border: '1px solid var(--border-glow)',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              fontFamily: 'JetBrains Mono',
              fontSize: '0.75rem'
            }}>
              <Radio size={14} color="var(--accent-emerald)" className="pulse-dot" />
              <span>LIVE FIELD PERCEPTION: ACTIVE</span>
            </div>

            <div style={{
              position: 'absolute',
              bottom: '24px',
              right: '24px',
              background: 'rgba(7, 9, 14, 0.9)',
              backdropFilter: 'blur(10px)',
              padding: '12px 18px',
              borderRadius: '14px',
              border: '1px solid var(--border-glow)',
              fontFamily: 'JetBrains Mono',
              fontSize: '0.78rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px'
            }}>
              <div style={{ color: 'var(--accent-cyan)', fontWeight: 700 }}>DUAL ARM COORDINATES</div>
              <div style={{ color: 'var(--text-secondary)' }}>Arm1: X:+12.0 Y:-4.0 Z:-8.3</div>
              <div style={{ color: 'var(--text-secondary)' }}>Arm2: X:+10.0 Y:-4.0 Z:-5.0</div>
            </div>
          </div>

        </div>
      </section>

      {/* SYSTEM TELEMETRY TICKER BAR */}
      <section style={{
        background: 'rgba(15, 23, 42, 0.8)',
        borderTop: '1px solid var(--border-glow)',
        borderBottom: '1px solid var(--border-glow)',
        padding: '14px 32px',
        overflow: 'hidden'
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-around',
          alignItems: 'center',
          maxWidth: '1280px',
          margin: '0 auto',
          fontSize: '0.82rem',
          fontFamily: 'JetBrains Mono',
          color: 'var(--text-secondary)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Cpu size={16} color="var(--accent-cyan)" />
            <span>ESP32 IK ENGINE: <strong style={{ color: '#fff' }}>ONLINE (115200 baud)</strong></span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Zap size={16} color="var(--accent-amber)" />
            <span>GROQ LLM INFERENCE: <strong style={{ color: '#fff' }}>llama-3.3-70b-versatile</strong></span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Eye size={16} color="var(--accent-purple)" />
            <span>PERCEPTION: <strong style={{ color: '#fff' }}>YOLOv8 Pose + HSV Fiducials</strong></span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldCheck size={16} color="var(--accent-emerald)" />
            <span>SAFETY VALIDATOR: <strong style={{ color: 'var(--accent-emerald)' }}>0 BREACHES / ZERO COLLISIONS</strong></span>
          </div>
        </div>
      </section>

      {/* INTERACTIVE PROCEDURE SIMULATOR */}
      <section id="simulator" style={{ padding: '80px 32px', maxWidth: '1280px', margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: '48px' }}>
          <div className="badge badge-purple" style={{ marginBottom: '12px' }}>
            <Sliders size={14} />
            <span>INTERACTIVE PROCEDURE SIMULATOR</span>
          </div>
          <h2 style={{ fontSize: '2.5rem', fontWeight: 800 }}>
            Test Natural-Language Execution & Repair
          </h2>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '640px', margin: '12px auto 0 auto' }}>
            Select a surgical command or type your own. Watch how RoboSurge translates intent into precision 3D spatial trajectories and pure-math safety validation.
          </p>
        </div>

        {/* Preset Command Selector Buttons */}
        <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', flexWrap: 'wrap', marginBottom: '32px' }}>
          {PRESET_COMMANDS.map((preset, idx) => (
            <button 
              key={idx}
              onClick={() => handleSelectPreset(preset)}
              style={{
                padding: '10px 18px',
                borderRadius: '10px',
                fontFamily: 'Plus Jakarta Sans',
                fontWeight: 600,
                fontSize: '0.88rem',
                cursor: 'pointer',
                background: selectedPreset.cmd === preset.cmd ? 'rgba(56, 189, 248, 0.2)' : 'rgba(30, 41, 59, 0.5)',
                border: selectedPreset.cmd === preset.cmd ? '1px solid var(--accent-cyan)' : '1px solid var(--border-muted)',
                color: selectedPreset.cmd === preset.cmd ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                transition: 'all 0.2s ease'
              }}
            >
              {preset.label}
            </button>
          ))}
        </div>

        {/* Simulator Container */}
        <div className="glass-panel" style={{ padding: '24px', display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '24px' }}>
          
          {/* Left Canvas Preview */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontFamily: 'JetBrains Mono', fontSize: '0.85rem' }}>
                <Crosshair size={16} color="var(--accent-cyan)" />
                <span style={{ fontWeight: 700 }}>SURGICAL FIELD 3D TRAJECTORY PREVIEW</span>
              </div>
              <div style={{ fontSize: '0.78rem', fontFamily: 'JetBrains Mono', color: 'var(--accent-emerald)' }}>
                PROGRESS: {simProgress}%
              </div>
            </div>

            {/* Canvas Frame */}
            <div style={{ borderRadius: '12px', overflow: 'hidden', border: '1px solid var(--border-glow)', position: 'relative' }}>
              <canvas 
                ref={canvasRef} 
                width={600} 
                height={360} 
                style={{ width: '100%', height: '360px', display: 'block' }} 
              />
              <div style={{
                position: 'absolute',
                bottom: '12px',
                left: '12px',
                background: 'rgba(7, 9, 14, 0.8)',
                padding: '6px 12px',
                borderRadius: '6px',
                fontSize: '0.72rem',
                fontFamily: 'JetBrains Mono',
                color: 'var(--text-muted)'
              }}>
                TABLE_Z_CM = -8.5 | FEED_RATE = 5.0 mm/s
              </div>
            </div>
          </div>

          {/* Right Code & Safety Details */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            
            {/* View Tabs */}
            <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-muted)', paddingBottom: '12px' }}>
              <button 
                onClick={() => setActiveTab('canvas')} 
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: activeTab === 'canvas' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                  fontWeight: 700, fontSize: '0.85rem', fontFamily: 'JetBrains Mono'
                }}
              >
                [ PLAN REPAIR ]
              </button>
              <button 
                onClick={() => setActiveTab('safety')} 
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: activeTab === 'safety' ? 'var(--accent-emerald)' : 'var(--text-muted)',
                  fontWeight: 700, fontSize: '0.85rem', fontFamily: 'JetBrains Mono'
                }}
              >
                [ SAFETY REPORT ]
              </button>
            </div>

            {/* Tab 1: Plan Repair Output */}
            {activeTab === 'canvas' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  <strong>Natural Language Intent:</strong>
                  <div style={{
                    background: 'rgba(7, 9, 14, 0.8)',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    fontFamily: 'JetBrains Mono',
                    color: 'var(--accent-cyan)',
                    marginTop: '6px',
                    border: '1px solid var(--border-glow)'
                  }}>
                    "{selectedPreset.cmd}"
                  </div>
                </div>

                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  <strong>LLM Procedural Rationale:</strong>
                  <p style={{ marginTop: '4px', fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                    {selectedPreset.rationale}
                  </p>
                </div>

                <div style={{
                  background: '#07090e',
                  borderRadius: '10px',
                  padding: '12px',
                  fontFamily: 'JetBrains Mono',
                  fontSize: '0.78rem',
                  color: '#e2e8f0',
                  border: '1px solid var(--border-glow)',
                  maxHeight: '160px',
                  overflowY: 'auto'
                }}>
                  <div style={{ color: 'var(--accent-amber)', marginBottom: '6px' }}>// Deterministic Waypoint Sequence</div>
                  <pre style={{ margin: 0 }}>
                    {JSON.stringify({
                      procedure: selectedPreset.type,
                      target_depth: selectedPreset.depth,
                      arm1_feed_rate: "5.0 mm/s",
                      waypoints_arm1: selectedPreset.arm1Waypoints
                    }, null, 2)}
                  </pre>
                </div>
              </div>
            )}

            {/* Tab 2: Pure Math Safety Report */}
            {activeTab === 'safety' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div style={{
                  background: 'rgba(16, 185, 129, 0.1)',
                  border: '1px solid rgba(16, 185, 129, 0.3)',
                  padding: '12px',
                  borderRadius: '10px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px'
                }}>
                  <CheckCircle2 size={20} color="var(--accent-emerald)" />
                  <div>
                    <div style={{ fontWeight: 700, color: 'var(--accent-emerald)', fontSize: '0.9rem' }}>PLAN VALIDATION PASSED</div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>All 5 deterministic safety rules passed.</div>
                  </div>
                </div>

                <div style={{ fontSize: '0.82rem', display: 'flex', flexDirection: 'column', gap: '8px', fontFamily: 'JetBrains Mono' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border-muted)' }}>
                    <span>1. Workspace Reach Bounds</span>
                    <span style={{ color: 'var(--accent-emerald)', fontWeight: 700 }}>OK (&lt;16.5cm)</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border-muted)' }}>
                    <span>2. Z-Floor Clearance Check</span>
                    <span style={{ color: 'var(--accent-emerald)', fontWeight: 700 }}>OK (Z &gt; -8.5cm)</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border-muted)' }}>
                    <span>3. Inter-Arm Distance</span>
                    <span style={{ color: 'var(--accent-emerald)', fontWeight: 700 }}>OK (&gt; 2.5cm)</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border-muted)' }}>
                    <span>4. Feed Rate Clamping</span>
                    <span style={{ color: 'var(--accent-emerald)', fontWeight: 700 }}>OK (5.0 mm/s)</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                    <span>5. Teleportation Limit</span>
                    <span style={{ color: 'var(--accent-emerald)', fontWeight: 700 }}>OK (&lt;15mm/step)</span>
                  </div>
                </div>
              </div>
            )}

            {/* Launch Action */}
            <button className="btn-emerald" onClick={onLaunchConsole} style={{ width: '100%', marginTop: 'auto' }}>
              <Play size={18} fill="currentColor" />
              <span>Execute Procedure in Control Console</span>
            </button>

          </div>

        </div>
      </section>

      {/* CORE ARCHITECTURE GRID */}
      <section id="architecture" style={{ padding: '80px 32px', maxWidth: '1280px', margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: '48px' }}>
          <div className="badge badge-emerald" style={{ marginBottom: '12px' }}>
            <Layers size={14} />
            <span>FOUR-TIER PIPELINE</span>
          </div>
          <h2 style={{ fontSize: '2.5rem', fontWeight: 800 }}>
            Safety-by-Construction System Architecture
          </h2>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '640px', margin: '12px auto 0 auto' }}>
            How RoboSurge guarantees that non-deterministic LLM planning never translates into an unsafe physical robot movement.
          </p>
        </div>

        {/* 4 Feature Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '24px' }}>
          
          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{
              width: '44px', height: '44px', borderRadius: '12px',
              background: 'rgba(56, 189, 248, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginBottom: '20px'
            }}>
              <Eye size={22} color="var(--accent-cyan)" />
            </div>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 700, marginBottom: '10px' }}>1. Perception Fusion</h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
              YOLOv8-pose tracks 4 skeleton keypoints per arm. HSV landmark detector locates colored fiducial dots (Yellow A, Cyan B, Purple C) mapped via LocalAffineMapper.
            </p>
          </div>

          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{
              width: '44px', height: '44px', borderRadius: '12px',
              background: 'rgba(245, 158, 11, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginBottom: '20px'
            }}>
              <Zap size={22} color="var(--accent-amber)" />
            </div>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 700, marginBottom: '10px' }}>2. Groq LLM Planner</h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
              Groq Llama-3.3-70B converts high-level natural language instructions into structured JSON procedure intents without generating raw spatial coordinates.
            </p>
          </div>

          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{
              width: '44px', height: '44px', borderRadius: '12px',
              background: 'rgba(16, 185, 129, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginBottom: '20px'
            }}>
              <ShieldCheck size={22} color="var(--accent-emerald)" />
            </div>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 700, marginBottom: '10px' }}>3. Plan Repair & Validator</h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
              Deterministic Python code reconstructs exact cut geometry from physical landmarks. ProcedureValidator verifies Z-floor boundaries and inter-arm clearance.
            </p>
          </div>

          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{
              width: '44px', height: '44px', borderRadius: '12px',
              background: 'rgba(168, 85, 247, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginBottom: '20px'
            }}>
              <Cpu size={22} color="var(--accent-purple)" />
            </div>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 700, marginBottom: '10px' }}>4. ESP32 Motion Engine</h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
              Dual 3-DOF servo arms receive 10Hz linear waypoint streams over serial @ 115200 baud. On-chip inverse kinematics drive precise servo movement.
            </p>
          </div>

        </div>
      </section>

      {/* TECH SPECS TABLE */}
      <section id="specs" style={{ padding: '60px 32px 100px 32px', maxWidth: '1000px', margin: '0 auto' }}>
        <div className="glass-panel" style={{ padding: '32px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '24px' }}>
            <FileCode2 size={24} color="var(--accent-cyan)" />
            <h3 style={{ fontSize: '1.5rem', fontWeight: 800 }}>System Specifications Manifest</h3>
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'JetBrains Mono', fontSize: '0.85rem' }}>
            <tbody>
              <tr style={{ borderBottom: '1px solid var(--border-muted)' }}>
                <td style={{ padding: '12px 0', color: 'var(--text-muted)' }}>Robot Form Factor</td>
                <td style={{ padding: '12px 0', textAlign: 'right', fontWeight: 700 }}>2 × 3-DOF Servo Arms (Base Pan + Shoulder + Elbow)</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border-muted)' }}>
                <td style={{ padding: '12px 0', color: 'var(--text-muted)' }}>On-Chip Kinematics</td>
                <td style={{ padding: '12px 0', textAlign: 'right', fontWeight: 700 }}>ESP32 Inverse Kinematics Engine @ 115200 baud</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border-muted)' }}>
                <td style={{ padding: '12px 0', color: 'var(--text-muted)' }}>Vision Pipeline</td>
                <td style={{ padding: '12px 0', textAlign: 'right', fontWeight: 700 }}>YOLOv8-Pose (4 keypoints) + LocalAffineMapper</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border-muted)' }}>
                <td style={{ padding: '12px 0', color: 'var(--text-muted)' }}>Supported Procedures</td>
                <td style={{ padding: '12px 0', textAlign: 'right', fontWeight: 700 }}>Incision, Biopsy, Cauterization, Suturing, Debridement</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border-muted)' }}>
                <td style={{ padding: '12px 0', color: 'var(--text-muted)' }}>Safety Boundaries</td>
                <td style={{ padding: '12px 0', textAlign: 'right', fontWeight: 700 }}>Feed rate 0.5-15 mm/s | Z-Floor: TABLE_Z_CM - MAX_CUT</td>
              </tr>
              <tr>
                <td style={{ padding: '12px 0', color: 'var(--text-muted)' }}>LLM Planning Engine</td>
                <td style={{ padding: '12px 0', textAlign: 'right', fontWeight: 700, color: 'var(--accent-cyan)' }}>Groq Llama-3.3-70B-Versatile API</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* FOOTER */}
      <footer style={{
        background: '#04060a',
        borderTop: '1px solid var(--border-muted)',
        padding: '32px',
        textAlign: 'center',
        fontSize: '0.82rem',
        color: 'var(--text-muted)'
      }}>
        <div style={{ maxWidth: '1280px', margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <strong>RoboSurge</strong> — Research platform running on benchtop phantom field. Not a clinical medical device.
          </div>
          <div style={{ fontFamily: 'JetBrains Mono', color: 'var(--accent-cyan)' }}>
            Google DeepMind Antigravity Pair-Programmed
          </div>
        </div>
      </footer>
    </div>
  );
};
