public class TestApp {
    public static void main(String[] args) {
        try {
            // 模拟 Spring/JDK 等底层框架的代理调用
            frameworkInvoke();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    public static void frameworkInvoke() {
        try {
            businessLogic();
        } catch (Exception e) {
            throw new RuntimeException("Framework execution wrapped exception", e);
        }
    }

    public static void businessLogic() {
        String data = null;
        // 这里故意制造一个空指针异常 (NullPointerException)
        // 我们需要确保 Python 脚本能跨过上层的 RuntimeException，精准倒序定位到这一行
        if (data.equals("secret")) {
            System.out.println("Access Granted");
        }
    }
}