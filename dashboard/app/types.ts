export type Role = 'SHIPPER' | 'CUSTOMER' | 'ADMIN'

export interface User {
  id: string
  phone: string
  name: string
  role: Role
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

export interface Order {
  id: string
  order_code: string
  status: string
  recipient_phone: string
  recipient_name: string
  box: number
  station_device_id: string
  stored_at: string | null
  paid_at: string | null
  completed_at: string | null
  fee_vnd: number
  daily_rate_vnd: number
  deposit_code?: string | null
  pickup_otp?: string | null
}

export interface Payment {
  provider: 'payos' | 'momo_sandbox' | 'mock'
  order_code: string
  payos_order_code: number
  amount_vnd: number
  status: string
  checkout_url: string
  qr_code: string
}

export interface LockerBox {
  box: number
  size: 'S' | 'M' | 'TECH'
  business_status: string
  operational_status: string
  occupied: boolean | null
  door_closed: boolean | null
  order_code: string | null
  order_status: string | null
  stored_at: string | null
  daily_rate_vnd: number | null
}

export interface LockerStatus {
  device_id: string
  online: boolean
  boxes: LockerBox[]
}

export interface AuditLog {
  id: string
  action: string
  entity_type: string
  entity_id: string
  detail: Record<string, unknown>
  created_at: string
}

export interface RevenueSummary {
  today_vnd: number
  month_vnd: number
  total_vnd: number
  paid_transactions: number
}

export interface DailyRevenue {
  date: string
  amount_vnd: number
  transaction_count: number
}

export interface RevenueTransaction {
  id: string
  order_code: string
  provider: string
  amount_vnd: number
  paid_at: string
}

export interface AdminDashboard {
  revenue: RevenueSummary
  daily_revenue: DailyRevenue[]
  recent_transactions: RevenueTransaction[]
}
