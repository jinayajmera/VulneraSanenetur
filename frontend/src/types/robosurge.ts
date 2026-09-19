export interface SystemVitals {
  camera: 'LIVE' | 'ERROR' | 'OFFLINE';
  serial: 'CONNECTED' | 'DRY_RUN' | 'ERROR' | 'OFFLINE';
  groq: 'ACTIVE' | 'MISSING_KEY' | 'OFFLINE';
}

export interface ArmState {
  id: number;
  x: number;
  y: number;
  z: number;
  source: string;
}

export interface LandmarkState {
  name: string;
  x: number;
  y: number;
  z: number;
  conf: number;
}

export interface SceneStateData {
  arms: ArmState[];
  landmarks: LandmarkState[];
  tool_offset: number;
  table_z: number;
  safe_z: number;
}

export interface WaypointData {
  x: number;
  y: number;
  z: number;
  label: string;
  dwell_s?: number;
}

export interface ArmPlanData {
  id: number;
  role: string;
  feed: number;
  waypoints: WaypointData[];
}

export interface ProcedurePlanData {
  procedure: string;
  rationale: string;
  duration: number;
  safety_notes: string;
  arm1: ArmPlanData;
  arm2: ArmPlanData;
}

export interface ValidationData {
  ok: boolean;
  errors: string[];
  warnings: string[];
  summary?: string;
}

export interface PlanningStateData {
  command: string;
  plan: ProcedurePlanData | null;
  validation: ValidationData | null;
  serial_preview?: string[];
  nl_translation?: string;
  doctor_brief?: string;
  is_doctor_edited?: boolean;
}

export interface CalibrationData {
  scale_x: number;
  scale_y: number;
  offset_x_cm: number;
  offset_y_cm: number;
  tool_z_offset_cm: number;
}

export interface ArmExecutionResult {
  arm_id: number;
  status: 'OK' | 'ABORTED';
  aborted: boolean;
  steps_sent: number;
  duration_s: number;
  final_position: [number, number, number];
}

export interface ExecutionStateData {
  is_executing: boolean;
  last_results: Record<string, ArmExecutionResult> | null;
}

export interface LogEntry {
  time: string;
  tag: 'SYS' | 'CMD' | 'ALERT' | 'WARN' | 'EXEC' | string;
  message: string;
}

export interface StatusResponse {
  online: boolean;
  time: string;
  vitals: SystemVitals;
  scene: SceneStateData;
  calibration: CalibrationData;
  planning: PlanningStateData;
  execution: ExecutionStateData;
  logs: LogEntry[];
}

export interface UserAuth {
  token: string;
  role: 'admin' | 'doctor';
  username: string;
}
