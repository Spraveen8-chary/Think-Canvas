// Login / register page.
import { api } from "./api.js";

const $ = (id) => document.getElementById(id);
let registering = false;

function setMode(reg) {
  registering = reg;
  $("tabLogin").classList.toggle("on", !reg);
  $("tabRegister").classList.toggle("on", reg);
  $("nameRow").hidden = $("orgRow").hidden = !reg;
  $("name").required = reg;
  $("password").autocomplete = reg ? "new-password" : "current-password";
  $("submit").textContent = reg ? "Create account" : "Log in";
  $("error").textContent = "";
}
$("tabLogin").onclick = () => setMode(false);
$("tabRegister").onclick = () => setMode(true);

$("form").onsubmit = async (e) => {
  e.preventDefault();
  $("error").textContent = "";
  $("submit").disabled = true;
  try {
    if (registering) await api.register($("name").value, $("email").value, $("password").value, $("org").value);
    else await api.login($("email").value, $("password").value);
    location.href = "/";
  } catch (err) {
    $("error").textContent = err.message;
  } finally {
    $("submit").disabled = false;
  }
};

api.me().then(() => (location.href = "/")).catch(() => {});      // already logged in
