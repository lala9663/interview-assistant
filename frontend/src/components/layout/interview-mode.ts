import { computed, readonly, ref } from 'vue'

const inRoom = ref(false)
const menuShown = ref(false)

/**
 * 면접 모드: while an interview is in progress its room takes the whole window. The app's sidebar and top
 * bar fold away so a laptop screen shows only the interview; the room's header brings the menu back (and
 * folds it again). The room turns the mode on when it opens and off when it closes, and every room opens
 * folded.
 */
export const interviewMode = {
  /** the app's sidebar and top bar are folded away */
  focused: computed(() => inRoom.value && !menuShown.value),
  inRoom: readonly(inRoom),
  enter() {
    inRoom.value = true
    menuShown.value = false
  },
  leave() {
    inRoom.value = false
    menuShown.value = false
  },
  toggleMenu() {
    menuShown.value = !menuShown.value
  },
}
