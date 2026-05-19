import type { Paginated } from "~/types/responses";

export interface Task {
  id?: number;
  name: string;
  url: string;
  folder?: string;
  preset?: string;
  timer?: string;
  template?: string;
  cli?: string;
  download_mode?: string;
  subtitle_mode?: string;
  auto_start?: boolean;
  handler_enabled?: boolean;
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface TaskPatch {
  name?: string;
  url?: string;
  folder?: string;
  preset?: string;
  timer?: string;
  template?: string;
  cli?: string;
  download_mode?: string;
  subtitle_mode?: string;
  auto_start?: boolean;
  handler_enabled?: boolean;
  enabled?: boolean;
}

export type TaskList = Paginated<Task>;

export interface TaskInspectRequest {
  url: string;
  preset?: string;
  handler?: string;
  static_only?: boolean;
}

export interface TaskInspectSuccess {
  matched: true;
  handler: string;
  message: string;
}

export interface TaskInspectFailure {
  matched: false;
  message: string;
  error: string;
}

export type TaskInspectResponse = TaskInspectSuccess | TaskInspectFailure;

export interface TaskMetadataResponse {
  id: string;
  id_type: string | null;
  title: string | null;
  description: string;
  uploader: string;
  tags: Array<string>;
  year: number | null;
  thumbnails: Record<string, string>;
  json_file?: string;
  nfo_file?: string;
}

export interface ExportedTask extends Omit<
  Task,
  "id" | "created_at" | "updated_at" | "in_progress"
> {
  _type: string;
  _version: string;
}

export interface ErrorResponse {
  error: string;
  detail?: unknown;
}

export type task_item = Task;
export type exported_task = ExportedTask;
export type error_response = ErrorResponse;
