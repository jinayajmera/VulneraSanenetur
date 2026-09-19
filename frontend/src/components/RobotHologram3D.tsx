import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { Crosshair, Play, Pause, Cpu, Activity, Zap, Layers, Sparkles } from 'lucide-react';

export type HologramMode = 'ARM_KINEMATICS' | 'TARGET_SCANNER' | 'LASER_INCISION';

interface RobotHologram3DProps {
  initialMode?: HologramMode;
  className?: string;
  onTelemetryUpdate?: (data: {
    coords: { x: number; y: number; z: number };
    angles: { j1: number; j2: number; j3: number };
    target: 'A' | 'B' | 'C';
    mode: HologramMode;
  }) => void;
}

export const RobotHologram3D: React.FC<RobotHologram3DProps> = ({
  initialMode = 'ARM_KINEMATICS',
  className = '',
  onTelemetryUpdate
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activeMode, setActiveMode] = useState<HologramMode>(initialMode);
  const [activeTarget, setActiveTarget] = useState<'A' | 'B' | 'C'>('A');
  const [isRotating, setIsRotating] = useState<boolean>(true);
  const [armCoords, setArmCoords] = useState<{ x: number; y: number; z: number }>({ x: 10.2, y: 3.4, z: 5.1 });
  const [jointAngles, setJointAngles] = useState<{ j1: number; j2: number; j3: number }>({ j1: 34, j2: -18, j3: 45 });

  const modeRef = useRef<HologramMode>(activeMode);
  modeRef.current = activeMode;

  const targetRef = useRef<'A' | 'B' | 'C'>(activeTarget);
  targetRef.current = activeTarget;

  const rotatingRef = useRef<boolean>(isRotating);
  rotatingRef.current = isRotating;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // SCENE SETUP
    const scene = new THREE.Scene();

    // CAMERA - Adjusted for immersive wide background framing
    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || window.innerHeight;
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    
    // Position camera slightly offset so robot arm sits prominently in middle-right
    camera.position.set(2.2, 4.8, 8.8);
    camera.lookAt(0.8, 1.2, 0);

    // RENDERER with transparent alpha for seamless page background blending
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = false;
    container.appendChild(renderer.domElement);

    // LIGHTING
    const ambientLight = new THREE.AmbientLight(0x26685c, 1.4);
    scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0x53c0aa, 2.2);
    dirLight1.position.set(8, 14, 10);
    scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x0e473c, 1.6);
    dirLight2.position.set(-8, -4, -6);
    scene.add(dirLight2);

    const pointLight = new THREE.PointLight(0x38e5b0, 3.0, 15);
    pointLight.position.set(1.5, 3.5, 1.5);
    scene.add(pointLight);

    // ROOT 3D GROUP
    const mainGroup = new THREE.Group();
    // Offset slightly to the right side of the screen for ideal hero framing
    mainGroup.position.set(1.2, 0, 0);
    scene.add(mainGroup);

    // HIGH-CONTRAST RETRO-TACTICAL MATERIALS
    const robotBodyMat = new THREE.MeshStandardMaterial({
      color: 0x0a332a,
      metalness: 0.85,
      roughness: 0.25,
      emissive: 0x051b16,
      emissiveIntensity: 0.4,
    });

    const robotAccentMat = new THREE.MeshStandardMaterial({
      color: 0x1f7a68,
      metalness: 0.7,
      roughness: 0.3,
      emissive: 0x0c4237,
      emissiveIntensity: 0.6,
    });

    const jointMat = new THREE.MeshStandardMaterial({
      color: 0x06221c,
      metalness: 0.95,
      roughness: 0.15,
      emissive: 0x11463c,
    });

    const glowTealMat = new THREE.MeshBasicMaterial({
      color: 0x53c0aa,
      wireframe: true,
      transparent: true,
      opacity: 0.6,
    });

    const laserBeamMat = new THREE.MeshBasicMaterial({
      color: 0x108e68,
      transparent: true,
      opacity: 0.85,
    });

    // 1. SLEEK MINIMAL TACTICAL FLOOR CIRCLE (No heavy clunky grids)
    const floorRingGeo = new THREE.RingGeometry(3.6, 3.66, 64);
    const floorRingMat = new THREE.MeshBasicMaterial({
      color: 0x26685c,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.45,
    });
    const floorRing = new THREE.Mesh(floorRingGeo, floorRingMat);
    floorRing.rotation.x = Math.PI / 2;
    floorRing.position.y = -0.02;
    mainGroup.add(floorRing);

    const innerFloorRing = new THREE.Mesh(
      new THREE.RingGeometry(1.8, 1.84, 48),
      new THREE.MeshBasicMaterial({ color: 0x3fa792, side: THREE.DoubleSide, transparent: true, opacity: 0.35 })
    );
    innerFloorRing.rotation.x = Math.PI / 2;
    innerFloorRing.position.y = -0.01;
    mainGroup.add(innerFloorRing);

    // Dynamic Rotating Scanner Pulse Line
    const radarGeo = new THREE.BufferGeometry();
    radarGeo.setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(3.6, 0, 0)]);
    const radarLine = new THREE.Line(
      radarGeo,
      new THREE.LineBasicMaterial({ color: 0x53c0aa, transparent: true, opacity: 0.5 })
    );
    radarLine.position.y = 0.01;
    mainGroup.add(radarLine);

    // 2. HOLOGRAPHIC OPERATING BED
    const bedGeo = new THREE.BoxGeometry(4.2, 0.18, 2.2);
    const bedEdges = new THREE.EdgesGeometry(bedGeo);
    const bedWireframe = new THREE.LineSegments(
      bedEdges,
      new THREE.LineBasicMaterial({ color: 0x26685c, transparent: true, opacity: 0.6 })
    );
    bedWireframe.position.set(0, 0.4, 0);
    mainGroup.add(bedWireframe);

    // Operating Field Scan Ring
    const scanRing = new THREE.Mesh(
      new THREE.RingGeometry(1.4, 1.48, 32),
      new THREE.MeshBasicMaterial({ color: 0x38e5b0, side: THREE.DoubleSide, transparent: true, opacity: 0.5 })
    );
    scanRing.rotation.x = Math.PI / 2;
    scanRing.position.y = 0.41;
    mainGroup.add(scanRing);

    // 3. ANATOMICAL TARGET ANCHORS (Tag A, B, C)
    const targetPositions = {
      A: new THREE.Vector3(-1.1, 0.68, -0.4),
      B: new THREE.Vector3(0.0, 0.68, 0.3),
      C: new THREE.Vector3(1.1, 0.68, -0.2),
    };

    const targetMeshes: Record<string, THREE.Group> = {};
    Object.entries(targetPositions).forEach(([key, pos]) => {
      const tgGroup = new THREE.Group();
      tgGroup.position.copy(pos);

      // Diamond octahedron
      const octGeo = new THREE.OctahedronGeometry(0.2, 0);
      const octMat = new THREE.MeshStandardMaterial({
        color: key === 'A' ? 0x082923 : key === 'B' ? 0x15463c : 0x0c382f,
        wireframe: true,
        emissive: 0x53c0aa,
        emissiveIntensity: 0.8,
      });
      const octMesh = new THREE.Mesh(octGeo, octMat);
      tgGroup.add(octMesh);

      // Halo ring
      const ringMesh = new THREE.Mesh(
        new THREE.RingGeometry(0.24, 0.28, 24),
        new THREE.MeshBasicMaterial({
          color: 0x26685c,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.7,
        })
      );
      ringMesh.rotation.x = Math.PI / 2;
      ringMesh.position.y = -0.15;
      tgGroup.add(ringMesh);

      mainGroup.add(tgGroup);
      targetMeshes[key] = tgGroup;
    });

    // 4. MAIN SURGICAL ROBOTIC ARM (Primary Arm 1)
    const robotArm1 = new THREE.Group();
    robotArm1.position.set(-2.0, 0, 0);
    mainGroup.add(robotArm1);

    // Base Pedestal
    const baseCylinder = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.7, 0.42, 32), robotBodyMat);
    baseCylinder.position.y = 0.21;
    robotArm1.add(baseCylinder);

    const baseRingGlow = new THREE.Mesh(new THREE.TorusGeometry(0.62, 0.03, 16, 32), glowTealMat);
    baseRingGlow.rotation.x = Math.PI / 2;
    baseRingGlow.position.y = 0.38;
    robotArm1.add(baseRingGlow);

    // Turret
    const turretGroup = new THREE.Group();
    turretGroup.position.y = 0.42;
    robotArm1.add(turretGroup);

    const shoulderJoint = new THREE.Mesh(new THREE.SphereGeometry(0.34, 24, 24), jointMat);
    shoulderJoint.position.y = 0.22;
    turretGroup.add(shoulderJoint);

    // Upper Arm
    const upperArmGroup = new THREE.Group();
    upperArmGroup.position.y = 0.22;
    turretGroup.add(upperArmGroup);

    const upperArmMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.19, 1.7, 20), robotAccentMat);
    upperArmMesh.position.y = 0.85;
    upperArmGroup.add(upperArmMesh);

    // Elbow
    const elbowGroup = new THREE.Group();
    elbowGroup.position.y = 1.7;
    upperArmGroup.add(elbowGroup);

    const elbowMesh = new THREE.Mesh(new THREE.SphereGeometry(0.26, 20, 20), jointMat);
    elbowGroup.add(elbowMesh);

    // Forearm
    const forearmGroup = new THREE.Group();
    elbowGroup.add(forearmGroup);

    const forearmMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.14, 1.5, 20), robotBodyMat);
    forearmMesh.position.y = 0.75;
    forearmGroup.add(forearmMesh);

    // Wrist & Surgical Tool Head
    const wristGroup = new THREE.Group();
    wristGroup.position.y = 1.5;
    forearmGroup.add(wristGroup);

    const wristMesh = new THREE.Mesh(new THREE.SphereGeometry(0.18, 18, 18), jointMat);
    wristGroup.add(wristMesh);

    const toolHead = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.55, 18), robotAccentMat);
    toolHead.position.y = 0.32;
    toolHead.rotation.x = Math.PI;
    wristGroup.add(toolHead);

    // Tool Tip Laser Emitter
    const emitterTip = new THREE.Mesh(
      new THREE.SphereGeometry(0.06, 16, 16),
      new THREE.MeshBasicMaterial({ color: 0x38e5b0 })
    );
    emitterTip.position.y = 0.6;
    wristGroup.add(emitterTip);

    // 5. SECONDARY RETRACTOR ROBOTIC ARM
    const robotArm2 = new THREE.Group();
    robotArm2.position.set(2.0, 0, 0);
    mainGroup.add(robotArm2);

    const base2 = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.52, 0.38, 24), robotBodyMat);
    base2.position.y = 0.19;
    robotArm2.add(base2);

    const turret2 = new THREE.Group();
    turret2.position.y = 0.38;
    robotArm2.add(turret2);

    const arm2Upper = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.16, 1.45, 16), robotAccentMat);
    arm2Upper.position.y = 0.72;
    turret2.add(arm2Upper);

    const arm2Elbow = new THREE.Group();
    arm2Elbow.position.y = 1.45;
    turret2.add(arm2Elbow);

    const arm2Fore = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.12, 1.3, 16), robotBodyMat);
    arm2Fore.position.y = 0.65;
    arm2Elbow.add(arm2Fore);

    const arm2Tool = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.4, 0.14), jointMat);
    arm2Tool.position.y = 1.35;
    arm2Elbow.add(arm2Tool);

    // 6. DYNAMIC LASER BEAM
    const laserGeo = new THREE.CylinderGeometry(0.022, 0.022, 1, 12);
    const laserMesh = new THREE.Mesh(laserGeo, laserBeamMat);
    laserMesh.visible = true;
    mainGroup.add(laserMesh);

    // 7. FLOATING HOLOGRAPHIC PARTICLES
    const particleCount = 140;
    const particleGeo = new THREE.BufferGeometry();
    const particlePositions = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount * 3; i += 3) {
      particlePositions[i] = (Math.random() - 0.5) * 12;
      particlePositions[i + 1] = Math.random() * 5;
      particlePositions[i + 2] = (Math.random() - 0.5) * 10;
    }

    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    const particleMat = new THREE.PointsMaterial({
      color: 0x26685c,
      size: 0.07,
      transparent: true,
      opacity: 0.5,
    });
    const particleSystem = new THREE.Points(particleGeo, particleMat);
    mainGroup.add(particleSystem);

    // SMOOTH MOUSE PARALLAX ACROSS ENTIRE SCREEN
    let mouseX = 0;
    let mouseY = 0;
    let targetRotationX = 0;
    let targetRotationY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      const x = (e.clientX / window.innerWidth) - 0.5;
      const y = (e.clientY / window.innerHeight) - 0.5;
      mouseX = x * 2;
      mouseY = y * 2;
    };

    window.addEventListener('mousemove', handleMouseMove);

    // RESIZE OBSERVER
    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth || window.innerWidth;
      const h = container.clientHeight || window.innerHeight;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    window.addEventListener('resize', handleResize);
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    // ANIMATION LOOP
    let animId: number;
    const clock = new THREE.Clock();
    let lastTelemetryUpdate = 0;
    const tipWorldPos = new THREE.Vector3();

    const animate = () => {
      animId = requestAnimationFrame(animate);
      const elapsedTime = clock.getElapsedTime();

      // Fluid parallax damping
      targetRotationY = mouseX * 0.35;
      targetRotationX = mouseY * 0.15;
      mainGroup.rotation.y += (targetRotationY - mainGroup.rotation.y) * 0.04;
      mainGroup.rotation.x += (targetRotationX - mainGroup.rotation.x) * 0.04;

      // Subtle base rotation
      if (rotatingRef.current) {
        radarLine.rotation.y += 0.02;
      }

      // Animate Target Markers
      Object.entries(targetMeshes).forEach(([k, mesh]) => {
        mesh.rotation.y += 0.025;
        mesh.rotation.x = Math.sin(elapsedTime * 2 + (k === 'A' ? 0 : k === 'B' ? 1.5 : 3.0)) * 0.15;
        mesh.position.y = 0.68 + Math.sin(elapsedTime * 3 + (k === 'A' ? 0 : 2)) * 0.04;
      });

      // Pulse scan ring
      scanRing.scale.setScalar(1 + Math.sin(elapsedTime * 2.2) * 0.1);

      // Particle floating
      const positions = particleGeo.attributes.position.array as Float32Array;
      for (let i = 1; i < particleCount * 3; i += 3) {
        positions[i] += 0.002;
        if (positions[i] > 5) positions[i] = 0.1;
      }
      particleGeo.attributes.position.needsUpdate = true;

      // ROBOT ARM KINEMATICS
      const currentTargetKey = targetRef.current;
      const currentMode = modeRef.current;

      const j1 = Math.sin(elapsedTime * 0.75) * 0.35 + (currentTargetKey === 'A' ? 0.3 : currentTargetKey === 'B' ? 0.0 : -0.3);
      const j2 = -0.45 + Math.cos(elapsedTime * 1.0) * 0.2;
      const j3 = 0.75 + Math.sin(elapsedTime * 1.2) * 0.2;

      if (currentMode === 'TARGET_SCANNER') {
        turretGroup.rotation.y = Math.sin(elapsedTime * 2.2) * 0.75;
        upperArmGroup.rotation.z = -0.5 + Math.sin(elapsedTime * 1.6) * 0.2;
        elbowGroup.rotation.z = 0.8 + Math.cos(elapsedTime * 1.8) * 0.25;
        wristGroup.rotation.z = -0.3;
      } else if (currentMode === 'LASER_INCISION') {
        turretGroup.rotation.y = j1 + Math.sin(elapsedTime * 18) * 0.015;
        upperArmGroup.rotation.z = -0.55 + Math.cos(elapsedTime * 18) * 0.015;
        elbowGroup.rotation.z = 0.85;
        wristGroup.rotation.z = -0.3;
      } else {
        turretGroup.rotation.y = j1;
        upperArmGroup.rotation.z = j2;
        elbowGroup.rotation.z = j3;
        wristGroup.rotation.z = -j2 - j3 + 0.2;
      }

      // Secondary retractor arm counter-motion
      turret2.rotation.y = -Math.sin(elapsedTime * 0.5) * 0.22;
      turret2.rotation.z = 0.35 + Math.cos(elapsedTime * 0.7) * 0.12;
      arm2Elbow.rotation.z = -0.6 + Math.sin(elapsedTime * 0.8) * 0.12;

      // Laser Beam from Arm 1 tip to active target
      emitterTip.getWorldPosition(tipWorldPos);
      const targetWorldPos = new THREE.Vector3();
      targetMeshes[currentTargetKey].getWorldPosition(targetWorldPos);

      if (currentMode === 'LASER_INCISION' || currentMode === 'TARGET_SCANNER') {
        laserMesh.visible = true;
        const distance = tipWorldPos.distanceTo(targetWorldPos);
        laserMesh.scale.set(1, distance, 1);
        laserMesh.position.copy(tipWorldPos).lerp(targetWorldPos, 0.5);
        laserMesh.quaternion.setFromUnitVectors(
          new THREE.Vector3(0, 1, 0),
          targetWorldPos.clone().sub(tipWorldPos).normalize()
        );
        laserBeamMat.opacity = currentMode === 'LASER_INCISION' 
          ? 0.7 + Math.random() * 0.3 
          : 0.35 + Math.sin(elapsedTime * 8) * 0.2;
      } else {
        laserMesh.visible = false;
      }

      // Telemetry update hook
      if (elapsedTime - lastTelemetryUpdate > 0.1) {
        lastTelemetryUpdate = elapsedTime;
        const coords = {
          x: parseFloat((tipWorldPos.x * 5 + 10).toFixed(2)),
          y: parseFloat((tipWorldPos.z * 5).toFixed(2)),
          z: parseFloat((tipWorldPos.y * 3).toFixed(2)),
        };
        const angles = {
          j1: Math.round(turretGroup.rotation.y * (180 / Math.PI)),
          j2: Math.round(upperArmGroup.rotation.z * (180 / Math.PI)),
          j3: Math.round(elbowGroup.rotation.z * (180 / Math.PI)),
        };
        setArmCoords(coords);
        setJointAngles(angles);
        if (onTelemetryUpdate) {
          onTelemetryUpdate({ coords, angles, target: currentTargetKey, mode: currentMode });
        }
      }

      renderer.render(scene, camera);
    };

    animate();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', handleMouseMove);
      resizeObserver.disconnect();
      if (renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
      renderer.dispose();
      scene.clear();
    };
  }, [onTelemetryUpdate]);

  return (
    <div className={`w-full h-full relative pointer-events-none select-none ${className}`}>
      {/* 3D WebGL Canvas Layer */}
      <div ref={containerRef} className="absolute inset-0 w-full h-full pointer-events-auto" />

      {/* Floating Tactical Interactive Controls Bar (Bottom Right Dock) */}
      <div className="absolute bottom-6 right-6 z-20 pointer-events-auto flex flex-col items-end space-y-2.5 max-w-sm">
        
        {/* Real-time Telemetry Pill */}
        <div className="bg-[#c0eae1]/90 backdrop-blur-md px-3 py-1.5 rounded-lg border-2 border-[#26685c] text-[11px] font-mono text-[#082923] shadow-md flex items-center space-x-3">
          <div className="flex items-center space-x-1.5">
            <span className="w-2 h-2 rounded-full bg-[#108e68] animate-ping" />
            <span className="font-extrabold text-[#082923]">3D POSE:</span>
            <span>({armCoords.x.toFixed(1)}, {armCoords.y.toFixed(1)}, {armCoords.z.toFixed(1)}) cm</span>
          </div>
          <span className="text-[#26685c]">|</span>
          <div className="text-[10px] text-[#15463c] font-bold">
            LOCK: TAG {activeTarget}
          </div>
        </div>

        {/* Interactive Mode & Beacon Switcher Bar */}
        <div className="bg-[#53c0aa]/90 backdrop-blur-md p-2 rounded-xl border-2 border-[#26685c] shadow-xl flex flex-wrap items-center gap-1.5 font-mono text-xs">
          
          <button
            onClick={() => setActiveMode('ARM_KINEMATICS')}
            className={`px-2.5 py-1 rounded-lg border text-center transition-all flex items-center space-x-1 font-extrabold text-[10px] sm:text-[11px] ${
              activeMode === 'ARM_KINEMATICS'
                ? 'bg-[#082923] text-[#53c0aa] border-[#082923] shadow'
                : 'bg-[#c0eae1] hover:bg-[#b0ded4] text-[#082923] border-[#26685c]'
            }`}
          >
            <Activity className="w-3 h-3" />
            <span>IK MOTION</span>
          </button>

          <button
            onClick={() => setActiveMode('TARGET_SCANNER')}
            className={`px-2.5 py-1 rounded-lg border text-center transition-all flex items-center space-x-1 font-extrabold text-[10px] sm:text-[11px] ${
              activeMode === 'TARGET_SCANNER'
                ? 'bg-[#082923] text-[#53c0aa] border-[#082923] shadow'
                : 'bg-[#c0eae1] hover:bg-[#b0ded4] text-[#082923] border-[#26685c]'
            }`}
          >
            <Crosshair className="w-3 h-3" />
            <span>RADAR</span>
          </button>

          <button
            onClick={() => setActiveMode('LASER_INCISION')}
            className={`px-2.5 py-1 rounded-lg border text-center transition-all flex items-center space-x-1 font-extrabold text-[10px] sm:text-[11px] ${
              activeMode === 'LASER_INCISION'
                ? 'bg-[#082923] text-[#53c0aa] border-[#082923] shadow'
                : 'bg-[#c0eae1] hover:bg-[#b0ded4] text-[#082923] border-[#26685c]'
            }`}
          >
            <Zap className="w-3 h-3 text-amber-500" />
            <span>LASER</span>
          </button>

          <div className="h-4 w-px bg-[#26685c]/60 mx-1 hidden sm:block" />

          {/* Beacon Selector */}
          <div className="flex items-center space-x-1">
            {(['A', 'B', 'C'] as const).map((tag) => (
              <button
                key={tag}
                onClick={() => setActiveTarget(tag)}
                className={`px-2 py-0.5 rounded font-extrabold text-[10px] transition-all border ${
                  activeTarget === tag
                    ? 'bg-[#082923] text-[#38e5b0] border-[#082923] scale-105 shadow'
                    : 'bg-[#c0eae1] hover:bg-[#b0ded4] text-[#082923] border-[#26685c]'
                }`}
              >
                TAG {tag}
              </button>
            ))}
          </div>

          <button
            onClick={() => setIsRotating(!isRotating)}
            className="p-1 rounded bg-[#c0eae1] hover:bg-[#b0ded4] text-[#082923] border border-[#26685c] transition-colors ml-1"
            title={isRotating ? 'Pause rotation' : 'Resume rotation'}
          >
            {isRotating ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
          </button>
        </div>

      </div>
    </div>
  );
};
