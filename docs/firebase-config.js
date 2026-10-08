// 跨裝置同步用的 Firebase 專案設定（選用）。
// 留 null = 不啟用：不顯示登入、不載 Firebase SDK，閱讀器行為完全不變。
//
// 要啟用就把 Firebase 主控台「專案設定 → 你的應用程式」給的物件貼進來。
// 這些值本來就是公開的（瀏覽器裡看得到），放進 public repo 沒有問題；
// 真正擋人的是 ../firestore.rules，不是這把 apiKey。
window.FIREBASE_CONFIG = {
  apiKey: 'AIzaSyAFj_t5N5ceHiNF2jiMYgdgKJucOhG4sLs',
  authDomain: 'bible-reading-loop.firebaseapp.com',
  projectId: 'bible-reading-loop',
  appId: '1:1083289520618:web:3ffdb61d16a35cd44cca93',
  // Google One Tap 用的 OAuth 用戶端 ID（Firebase 啟用 Google 登入時自動建立的
  // Web client）。拿掉這行 = 不跳 One Tap，只留日程頁的登入按鈕。
  googleClientId: '1083289520618-ungbqkk0lhnfd1c4acpdcnn68k30ug20.apps.googleusercontent.com',
};
