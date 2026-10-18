<script setup lang="ts">
import QrcodeVue from 'qrcode.vue'
import type { AuditLog, AuthResponse, LockerStatus, Order, Payment, Role } from '~/types'

const { api, hydrate, logout, setAuth, token, user } = useApi()
const authMode = ref<'login' | 'register'>('login')
const authForm = reactive({ phone: '', name: '', password: '', role: 'CUSTOMER' as Role })
const orderForm = reactive({ recipient_phone: '', recipient_name: '', station_device_id: 'SB-001' })
const orders = ref<Order[]>([])
const locker = ref<LockerStatus | null>(null)
const audits = ref<AuditLog[]>([])
const payment = ref<Payment | null>(null)
const otpByOrder = reactive<Record<string, string>>({})
const depositOpenedForSimulation = reactive<Record<string, boolean>>({})
const manual = reactive({ box: 0, reason: 'Hỗ trợ khách hàng tại tủ' })
const busy = ref('')
const error = ref('')
const notice = ref('')
const showcase = [
  { src: '/images/smartbox-courier.jpg', alt: 'Shipper đặt kiện hàng vào tủ SmartBox', label: 'Gửi hàng' },
  { src: '/images/smartbox-pickup.jpg', alt: 'Người nhận mở ngăn tủ bằng điện thoại', label: 'Nhận hàng' },
  { src: '/images/smartbox-locker.jpg', alt: 'Tủ SmartBox năm ngăn tại sảnh tòa nhà', label: 'Lưu tại tủ' },
]
const movingShowcase = [...showcase, ...showcase]
let pollTimer: ReturnType<typeof setInterval> | undefined

const roleLabel = computed(() => ({ SHIPPER: 'Shipper', CUSTOMER: 'Người nhận', ADMIN: 'Vận hành' }[user.value?.role || 'CUSTOMER']))
const activeOrders = computed(() => orders.value.filter((item) => !['COMPLETED', 'CANCELLED'].includes(item.status)))
const money = (value: number) => new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(value)
const date = (value: string | null) => value ? new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '—'

function translateStatus(value: string) {
  return ({ RESERVED: 'Chờ gửi hàng', DEPOSIT_AUTHORIZED: 'Đang mở tủ', DEPOSIT_OPEN: 'Tủ đang mở', STORED: 'Đang lưu tại tủ', PAYMENT_PENDING: 'Chờ thanh toán', PAID: 'Đã thanh toán', PICKUP_AUTHORIZED: 'Đang mở tủ', PICKUP_OPEN: 'Tủ đang mở', COMPLETED: 'Đã nhận hàng', CANCELLED: 'Đã hủy', MANUAL_REVIEW: 'Cần xử lý', AVAILABLE: 'Trống', OCCUPIED: 'Đang dùng', OUT_OF_SERVICE: 'Bảo trì' } as Record<string, string>)[value] || value
}

function flash(message: string, isError = false) {
  if (isError) error.value = message
  else notice.value = message
  window.setTimeout(() => { error.value = ''; notice.value = '' }, 5000)
}

function apiError(err: unknown) {
  const value = err as { data?: { detail?: string }, message?: string }
  const detail = value.data?.detail || value.message || 'Không thể kết nối máy chủ'
  return ({ invalid_credentials: 'Số điện thoại hoặc mật khẩu không đúng.', phone_already_registered: 'Số điện thoại đã đăng ký.', invalid_otp: 'Mã OTP không đúng.', payment_required: 'Vui lòng thanh toán trước.', no_available_compartment: 'Hiện không còn ngăn tủ trống.', door_simulation_disabled: 'Chức năng giả lập cửa đang bị tắt trên máy chủ.', open_compartment_first: 'Hãy bấm mở ngăn trước khi giả lập đóng cửa.' } as Record<string, string>)[detail] || detail
}

function apiErrorDetail(err: unknown) {
  return (err as { data?: { detail?: string } }).data?.detail
}

async function run(key: string, action: () => Promise<void>) {
  busy.value = key; error.value = ''
  try { await action() } catch (err) { flash(apiError(err), true) } finally { busy.value = '' }
}

async function submitAuth() {
  const mode = authMode.value
  busy.value = 'auth'; error.value = ''
  try {
    const path = mode === 'login' ? '/api/v1/auth/login' : '/api/v1/auth/register'
    const body = mode === 'login' ? { phone: authForm.phone, password: authForm.password } : authForm
    setAuth(await api<AuthResponse>(path, { method: 'POST', body })); await refresh()
  } catch (err) {
    if (mode === 'register' && apiErrorDetail(err) === 'phone_already_registered') {
      authMode.value = 'login'
      authForm.password = ''
      flash('Tài khoản đã tồn tại. Hãy đăng nhập bằng mật khẩu đã tạo trước đó.', true)
    } else {
      flash(apiError(err), true)
    }
  } finally {
    busy.value = ''
  }
}

async function refresh(quiet = false) {
  if (!token.value) return
  try {
    const tasks: Promise<unknown>[] = [api<Order[]>('/api/v1/orders').then((data) => { orders.value = data })]
    if (user.value?.role === 'ADMIN') {
      tasks.push(api<LockerStatus>('/api/v1/lockers/SB-001/status').then((data) => { locker.value = data }))
      tasks.push(api<AuditLog[]>('/api/v1/admin/audit-logs').then((data) => { audits.value = data }))
    }
    await Promise.all(tasks)
  } catch (err) { if (!quiet) flash(apiError(err), true) }
}

async function createOrder() {
  await run('create-order', async () => {
    const created = await api<Order>('/api/v1/orders', { method: 'POST', body: orderForm })
    orderForm.recipient_name = ''; orderForm.recipient_phone = ''; await refresh(true)
    flash(`Tạo đơn ${created.order_code} thành công. Mã gửi: ${created.deposit_code}`)
  })
}

async function authorizeDeposit(order: Order) {
  await run(`deposit-${order.id}`, async () => {
    await api(`/api/v1/orders/${order.order_code}/deposit/authorize`, { method: 'POST' })
    depositOpenedForSimulation[order.id] = true
    flash(`Đã gửi lệnh mở ngăn ${order.box + 1}.`); await refresh(true)
  })
}

async function simulateDepositClose(order: Order) {
  await run(`close-${order.id}`, async () => {
    await api(`/api/v1/orders/${order.order_code}/deposit/simulate-close`, { method: 'POST' })
    delete depositOpenedForSimulation[order.id]
    flash(`Đã giả lập đóng ngăn ${order.box + 1}. Đơn hàng đã được lưu.`)
    await refresh(true)
  })
}

async function createPayment(order: Order) {
  await run(`payment-${order.id}`, async () => { payment.value = await api<Payment>(`/api/v1/orders/${order.order_code}/payments`, { method: 'POST' }) })
}

async function confirmMock(orderCode: string) {
  await run('mock-payment', async () => {
    await api(`/api/v1/orders/${orderCode}/payments/mock-confirm`, { method: 'POST' })
    payment.value = null; flash('Thanh toán demo đã được xác nhận.'); await refresh(true)
  })
}

async function pickup(order: Order) {
  await run(`pickup-${order.id}`, async () => {
    await api(`/api/v1/orders/${order.order_code}/pickup`, { method: 'POST', body: { otp: otpByOrder[order.id] || '' } })
    otpByOrder[order.id] = ''; flash(`Đã gửi lệnh mở ngăn ${order.box + 1}.`); await refresh(true)
  })
}

async function manualUnlock() {
  await run('manual', async () => {
    await api('/api/v1/lockers/SB-001/manual-unlock', { method: 'POST', body: manual }); flash(`Đã gửi lệnh mở ngăn ${manual.box + 1}.`)
  })
}

function signOut() { logout(); orders.value = []; locker.value = null; audits.value = [] }
onMounted(async () => { hydrate(); await refresh(true); pollTimer = setInterval(() => refresh(true), 5000) })
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <main>
    <header class="topbar">
      <a class="brand" href="#top" aria-label="SmartBox"><span class="brand-mark"><i /><i /><i /></span><span>SMARTBOX</span></a>
      <div v-if="user" class="user-area"><span class="status-dot" /><span class="user-copy"><b>{{ user.name }}</b><small>{{ roleLabel }}</small></span><button class="icon-button" title="Đăng xuất" @click="signOut">↗</button></div>
      <span v-else class="system-status"><i /> SB-001 sẵn sàng</span>
    </header>
    <div v-if="notice || error" class="toast" :class="{ error: !!error }">{{ error || notice }}</div>

    <section v-if="!user" id="top" class="auth-shell">
      <div class="auth-layout">
        <div class="hero-copy">
          <h1>Tủ nhận hàng<br><em>tự phục vụ.</em></h1>
          <p class="hero-lead">Uy tín tạo niềm tin.</p>
          <div class="image-marquee" aria-label="Quy trình sử dụng SmartBox">
            <div class="image-track">
              <figure v-for="(item, index) in movingShowcase" :key="`${item.src}-${index}`">
                <img :src="item.src" :alt="index < showcase.length ? item.alt : ''" :aria-hidden="index >= showcase.length" loading="eager">
                <figcaption><span>{{ String((index % showcase.length) + 1).padStart(2, '0') }}</span>{{ item.label }}</figcaption>
              </figure>
            </div>
          </div>
          <ol class="process-line"><li><b>01</b> Tạo đơn</li><li><b>02</b> Gửi vào tủ</li><li><b>03</b> Thanh toán</li><li><b>04</b> Nhận hàng</li></ol>
        </div>
        <form class="auth-card" @submit.prevent="submitAuth">
          <div class="auth-tabs"><button type="button" :class="{ active: authMode === 'login' }" @click="authMode = 'login'">Đăng nhập</button><button type="button" :class="{ active: authMode === 'register' }" @click="authMode = 'register'">Tạo tài khoản</button></div>
          <div class="card-intro"><p class="eyebrow">TÀI KHOẢN</p><h2>{{ authMode === 'login' ? 'Đăng nhập SmartBox' : 'Tạo tài khoản' }}</h2></div>
          <label v-if="authMode === 'register'">Họ và tên<input v-model="authForm.name" required minlength="2" placeholder="Nguyễn Văn An"></label>
          <label>Số điện thoại<input v-model="authForm.phone" required inputmode="tel" placeholder="09xx xxx xxx"></label>
          <label>Mật khẩu<input v-model="authForm.password" required minlength="8" type="password" placeholder="Tối thiểu 8 ký tự"></label>
          <label v-if="authMode === 'register'">Vai trò<select v-model="authForm.role"><option value="CUSTOMER">Người nhận</option><option value="SHIPPER">Shipper</option></select></label>
          <button class="primary full" :disabled="busy === 'auth'">{{ busy === 'auth' ? 'Đang xử lý…' : authMode === 'login' ? 'Đăng nhập' : 'Tạo tài khoản' }} <span>→</span></button><p class="security-note"><i /> Không chia sẻ mật khẩu hoặc OTP.</p>
        </form>
      </div>
    </section>

    <template v-else>
      <section class="page-heading"><div><p class="eyebrow">{{ user.role === 'SHIPPER' ? 'SHIPPER' : user.role === 'CUSTOMER' ? 'NGƯỜI NHẬN' : 'VẬN HÀNH' }}</p><h1>{{ user.role === 'SHIPPER' ? 'Đơn giao hàng' : user.role === 'CUSTOMER' ? 'Kiện hàng của bạn' : 'Trạm SB-001' }}</h1></div><button class="secondary" @click="refresh()">Cập nhật <span>↻</span></button></section>
      <section v-if="user.role === 'SHIPPER'" class="workspace split">
        <form class="panel create-panel" @submit.prevent="createOrder"><p class="eyebrow">TẠO ĐƠN MỚI</p><h2>Thông tin người nhận</h2><label>Họ và tên<input v-model="orderForm.recipient_name" required placeholder="Tên người nhận"></label><label>Số điện thoại<input v-model="orderForm.recipient_phone" required inputmode="tel" placeholder="09xx xxx xxx"></label><label>Trạm tủ<select v-model="orderForm.station_device_id"><option value="SB-001">SmartBox 001 · Trạm demo</option></select></label><button class="primary full" :disabled="busy === 'create-order'">Tạo đơn và giữ ngăn <span>→</span></button></form>
        <div class="panel"><div class="panel-head"><div><p class="eyebrow">ĐƠN HÀNG</p><h2>Đang xử lý</h2></div><span class="count">{{ activeOrders.length }} đơn</span></div><div v-if="!orders.length" class="empty">Chưa có đơn hàng. Tạo đơn đầu tiên ở bên trái.</div>
          <article v-for="order in orders" :key="order.id" class="order-card"><div class="order-top"><div><small>MÃ ĐƠN</small><strong>#{{ order.order_code }}</strong></div><span class="pill" :data-status="order.status">{{ translateStatus(order.status) }}</span></div><div class="order-grid"><p><small>NGƯỜI NHẬN</small>{{ order.recipient_name }}<br><span>{{ order.recipient_phone }}</span></p><p><small>VỊ TRÍ</small>Ngăn {{ order.box + 1 }}<br><span>{{ order.station_device_id }}</span></p><p v-if="order.deposit_code"><small>MÃ GỬI HÀNG</small><b class="code">{{ order.deposit_code }}</b></p></div><div class="order-actions"><button v-if="order.status === 'RESERVED' && !depositOpenedForSimulation[order.id]" class="primary compact" :disabled="busy === `deposit-${order.id}`" @click="authorizeDeposit(order)">Mở ngăn để gửi hàng →</button><button v-if="depositOpenedForSimulation[order.id] || ['DEPOSIT_AUTHORIZED', 'DEPOSIT_OPEN'].includes(order.status)" class="secondary compact" :disabled="busy === `close-${order.id}`" @click="simulateDepositClose(order)">{{ busy === `close-${order.id}` ? 'Đang giả lập…' : 'Giả lập đóng cửa' }} <span>✓</span></button></div></article>
        </div>
      </section>

      <section v-if="user.role === 'CUSTOMER'" class="workspace"><div v-if="!orders.length" class="panel empty large"><span class="empty-icon">◇</span><h2>Chưa có kiện hàng</h2><p>Đơn gửi tới số {{ user.phone }} sẽ xuất hiện tại đây.</p></div>
        <article v-for="order in orders" :key="order.id" class="customer-order"><div class="package-visual"><span class="locker-number">{{ String(order.box + 1).padStart(2, '0') }}</span><i class="locker-line" /><b>{{ order.station_device_id }}</b><small>NGĂN TỦ CỦA BẠN</small></div><div class="package-info"><div class="order-top"><div><p class="eyebrow">KIỆN HÀNG #{{ order.order_code }}</p><h2>{{ translateStatus(order.status) }}</h2></div><span class="pill" :data-status="order.status">{{ order.status }}</span></div><div class="facts"><p><small>NGƯỜI NHẬN</small>{{ order.recipient_name }}</p><p><small>GỬI VÀO TỦ</small>{{ date(order.stored_at) }}</p><p><small>PHỤ PHÍ QUÁ HẠN</small><b>{{ money(order.fee_vnd) }}</b></p></div><button v-if="order.status === 'STORED' && order.fee_vnd > 0" class="primary" :disabled="busy === `payment-${order.id}`" @click="createPayment(order)">Thanh toán phụ phí <span>→</span></button><div v-if="order.pickup_otp && ((order.status === 'STORED' && order.fee_vnd === 0) || order.status === 'PAID')" class="otp-row"><label>OTP nhận hàng<input v-model="otpByOrder[order.id]" maxlength="8" inputmode="numeric" :placeholder="`OTP: ${order.pickup_otp}`"></label><button class="primary" :disabled="busy === `pickup-${order.id}`" @click="pickup(order)">Mở tủ →</button></div><p v-if="order.status === 'COMPLETED'" class="complete-note">✓ Kiện hàng đã được nhận lúc {{ date(order.completed_at) }}</p></div></article>
      </section>

      <section v-if="user.role === 'ADMIN'" class="workspace admin-grid"><div class="panel station-panel"><div class="panel-head"><div><p class="eyebrow">TRẠNG THÁI TỦ</p><h2>5 ngăn tại SB-001</h2></div><span class="online-badge" :class="{ offline: !locker?.online }"><i /> {{ locker?.online ? 'Đang kết nối' : 'Mất kết nối' }}</span></div><div class="locker-map"><div v-for="box in locker?.boxes" :key="box.box" class="locker-cell" :class="box.business_status.toLowerCase()"><b>{{ String(box.box + 1).padStart(2, '0') }}</b><span>{{ translateStatus(box.business_status) }}</span><small>{{ box.door_closed === false ? 'Cửa đang mở' : 'Cửa đóng' }}</small></div></div></div>
        <form class="panel" @submit.prevent="manualUnlock"><p class="eyebrow">MỞ THỦ CÔNG</p><h2>Chọn ngăn tủ</h2><p class="muted">Lệnh mở và lý do sẽ được lưu vào nhật ký.</p><label>Ngăn tủ<select v-model.number="manual.box"><option v-for="n in 5" :key="n" :value="n - 1">Ngăn {{ n }}</option></select></label><label>Lý do<textarea v-model="manual.reason" required minlength="5" rows="3" /></label><button class="danger full" :disabled="busy === 'manual'">Mở ngăn tủ</button></form>
        <div class="panel audit-panel"><div class="panel-head"><div><p class="eyebrow">NHẬT KÝ HỆ THỐNG</p><h2>Hoạt động gần đây</h2></div></div><div class="audit-list"><div v-for="item in audits.slice(0, 20)" :key="item.id"><span class="audit-mark" /><p><b>{{ item.action.replaceAll('_', ' ') }}</b><small>{{ item.entity_type }} · {{ item.entity_id }}</small></p><time>{{ date(item.created_at) }}</time></div></div></div></section>
    </template>

    <footer><span>SMARTBOX / PHASE 1</span><p>ESP32-S3 · 5 ngăn tủ · payOS</p><a href="mailto:support@smartbox.id.vn">support@smartbox.id.vn</a></footer>
    <div v-if="payment" class="modal-backdrop" @click.self="payment = null"><section class="payment-modal"><button class="modal-close" @click="payment = null">×</button><p class="eyebrow">THANH TOÁN</p><h2>Quét QR để nhận hàng</h2><p class="payment-amount">{{ money(payment.amount_vnd) }}</p><div class="qr-wrap"><QrcodeVue :value="payment.qr_code || payment.checkout_url" :size="220" level="M" /></div><p class="payment-hint">{{ payment.provider === 'momo_sandbox' ? 'Dùng ứng dụng MoMo Test để quét mã. Đây là giao dịch sandbox, không trừ tiền thật.' : 'Quét mã bằng ứng dụng ngân hàng. Trạng thái đơn sẽ tự cập nhật sau khi thanh toán.' }}</p><a v-if="payment.checkout_url" class="secondary full link-button" :href="payment.checkout_url" target="_blank">Mở trang thanh toán {{ payment.provider === 'momo_sandbox' ? 'MoMo Sandbox' : 'payOS' }} ↗</a><button v-if="payment.provider === 'mock'" class="primary full" :disabled="busy === 'mock-payment'" @click="confirmMock(payment.order_code)">Xác nhận thanh toán demo</button></section></div>
  </main>
</template>
