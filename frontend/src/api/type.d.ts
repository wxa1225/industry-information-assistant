/**
 * Copyright © 2026  版权所有
 * 未经授权，禁止转售或仿制。
 */

declare namespace API {
  type Result<T> = T & {
    status: 'success' | 'error'
    message: string
  }
}
