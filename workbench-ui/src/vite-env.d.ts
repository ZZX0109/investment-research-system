/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API origin the workbench calls directly in dev (any frontend port).
   *  Defaults to http://127.0.0.1:8000; set when the API runs on another port. */
  readonly VITE_API_ORIGIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
