/**
 * Copyright © 2026  版权所有
 * 未经授权，禁止转售或仿制。
 */

/// <reference types="vite/client" />

interface Window {
  $app: import('antd/es/app/context').useAppProps
  $showLoading: (options?: { title?: string }) => void
  $hideLoading: () => void
}
