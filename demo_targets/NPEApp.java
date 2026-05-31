public class NPEApp {
    public static void main(String[] args) {
        String data = null;
        process(data);
    }
    public static void process(String s) {
        // 这里的 s.trim() 会在运行时抛出 NPE
        if (s.trim().length() > 0) {
            System.out.println("Processing: " + s);
        }
    }
}
