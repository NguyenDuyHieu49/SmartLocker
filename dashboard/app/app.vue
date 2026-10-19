<script setup lang="ts">
useHead({
  titleTemplate: (title) => title ? `${title} · SmartBox` : 'SmartBox · Tủ nhận hàng thông minh',
  meta: [
    { name: 'description', content: 'Tạo đơn, gửi hàng, thanh toán và nhận hàng tại tủ SmartBox.' },
    { name: 'theme-color', content: '#f3f4ee' },
  ],
})
</script>

<template>
  <NuxtPage />
</template>
