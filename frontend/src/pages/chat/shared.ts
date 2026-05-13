/**
 * Copyright © 2026  版权所有
 * 未经授权，禁止转售或仿制。
 */

import { PageTransportKey } from '@/utils'

export type ChatEnterData = {
  message: string
}

export const transportToChatEnter = Symbol() as PageTransportKey<{
  data: ChatEnterData
}>

let id = 0

export const createChatId = () => {
  return ++id
}

export function createChatIdText(id: number) {
  return `chat-item-${id}`
}
