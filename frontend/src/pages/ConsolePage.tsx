import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Header } from '../components/Header';
import { VisionFeed } from '../components/VisionFeed';
import { WorkspaceVisualizer } from '../components/WorkspaceVisualizer';
import { CommandConsole } from '../components/CommandConsole';
import { PlanInspector } from '../components/PlanInspector';
import { ExecutionCard } from '../components/ExecutionCard';
import { ActivityLog } from '../components/ActivityLog';
import { CalibrationModal } from '../components/CalibrationModal';
import { LoginModal } from '../components/LoginModal';
import { ApiService } from '../services/api';
import { StatusResponse, UserAuth } from '../types/robosurge';

const defaultStatus: StatusResponse = {
  online: false,
  time: '--:--:--',
  vitals: {
    camera: 'OFFLINE',
    serial: 'OFFLINE',
    groq: 'OFFLINE',
  },
  scene: {
    arms: [],
    landmarks: [],
    tool_offset: 0.0,
    table_z: -0.5,
    safe_z: 5.0,
  },
  calibration: {
    scale_x: 1.0,
    scale_y: 1.0,
    offset_x_cm: 0.0,
    offset_y_cm: 0.0,
    tool_z_offset_cm: 0.0,
  },
  planning: {
    command: '',
    plan: null,
    validation: null,
    serial_preview: [],
  },
  execution: {
    is_executing: false,
    last_results: null,
  },
  logs: [],
};

interface ConsolePageProps {
  user: UserAuth | null;
  setUser: (u: UserAuth | null) => void;
}

export const ConsolePage: React.FC<ConsolePageProps> = ({ user, setUser }) => {
  const navigate = useNavigate();
  const [status, setStatus] = useState<StatusResponse>(defaultStatus);
  const [selectedLandmark, setSelectedLandmark] = useState<string>('landmark_A');
  const [isPlanning, setIsPlanning] = useState(false);
  const [isCalibOpen, setIsCalibOpen] = useState(false);
  const [isLoginOpen, setIsLoginOpen] = useState(false);

  // Fetch status callback
  const fetchStatus = useCallback(async () => {
    try {
      const data = await ApiService.getStatus();
      setStatus(data);
    } catch {
      setStatus((prev) => ({
        ...prev,
        online: false,
        vitals: { ...prev.vitals, camera: 'OFFLINE' },
      }));
    }
  }, []);

  // Poll status every 800ms
  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 800);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // Handle Command Submit
  const handleCommandSubmit = async (cmd: string) => {
    setIsPlanning(true);
    try {
      await ApiService.sendCommand(cmd);
      await fetchStatus();
    } catch (e: any) {
      alert(`Planning Error: ${e.message}`);
    } finally {
      setIsPlanning(false);
    }
  };

  const handleSelectLandmark = (name: string) => {
    setSelectedLandmark(name);
  };

  return (
    <div className="h-screen max-h-screen overflow-hidden bg-[#a8dcd1] text-[#0f332c] flex flex-col selection:bg-[#53c0aa] selection:text-[#082923]">
      {/* Header Bar */}
      <Header
        vitals={status.vitals}
        user={user}
        onOpenCalibration={() => setIsCalibOpen(true)}
        onOpenLogin={() => setIsLoginOpen(true)}
        onRefresh={fetchStatus}
        onAbortSuccess={fetchStatus}
      />

      {/* Main Content Area - Locked into 100vh with 3 proportional sections (0 page scroll) */}
      <main className="flex-1 w-full max-w-[1920px] mx-auto p-1.5 sm:p-2 flex flex-col gap-1.5 overflow-hidden min-h-0">
        
        {/* Top Visual Row: Camera Feed (Left 7) & Vitals Monitor (Right 5) */}
        <div className="flex-[1.15] grid grid-cols-1 lg:grid-cols-12 gap-1.5 min-h-0 overflow-hidden">
          <div className="lg:col-span-7 xl:col-span-7 h-full min-h-0 overflow-hidden">
            <VisionFeed
              scene={status.scene}
              cameraStatus={status.vitals.camera}
              onSelectLandmark={handleSelectLandmark}
            />
          </div>
          <div className="lg:col-span-5 xl:col-span-5 h-full min-h-0 overflow-hidden">
            <WorkspaceVisualizer
              scene={status.scene}
              plan={status.planning.plan}
              onSelectLandmark={handleSelectLandmark}
            />
          </div>
        </div>

        {/* Middle Row: Surgical Command Console (Compact 1-row bar) */}
        <div className="flex-shrink-0">
          <CommandConsole
            onCommandSubmit={handleCommandSubmit}
            isPlanning={isPlanning}
            selectedLandmark={selectedLandmark}
          />
        </div>

        {/* Execution Active / Completed Card */}
        {(status.execution.is_executing || status.execution.last_results) && (
          <div className="flex-shrink-0">
            <ExecutionCard
              execution={status.execution}
              onAbort={() => ApiService.abort(false)}
            />
          </div>
        )}

        {/* Bottom Row: Plan Inspector (Left 7) & Activity Console Logs (Right 5) */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-1.5 min-h-0 overflow-hidden">
          <div className="lg:col-span-7 xl:col-span-7 h-full min-h-0 overflow-hidden">
            <PlanInspector
              planning={status.planning}
              isExecuting={status.execution.is_executing}
              onExecuteSuccess={fetchStatus}
            />
          </div>
          <div className="lg:col-span-5 xl:col-span-5 h-full min-h-0 overflow-hidden">
            <ActivityLog logs={status.logs} />
          </div>
        </div>
      </main>

      {/* Modals */}
      <CalibrationModal
        isOpen={isCalibOpen}
        onClose={() => setIsCalibOpen(false)}
        calibration={status.calibration}
        onUpdate={fetchStatus}
      />

      <LoginModal
        isOpen={isLoginOpen}
        onClose={() => setIsLoginOpen(false)}
        currentUser={user}
        onLoginSuccess={(u) => setUser(u)}
        onLogout={() => {
          ApiService.clearToken();
          setUser(null);
        }}
      />
    </div>
  );
};
